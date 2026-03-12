import os
import math
import requests
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import FastAPI
from pydantic import BaseModel
from google.cloud import firestore


# Calculate the cosine similarity between two vectors (user preferences vs book genres)
def calculate_cosine_similarity(user_vector: dict, book_vector: dict):
    # Find the intersection of genres
    intersection = set(user_vector.keys()) & set(book_vector.keys())

    # Calculate the numerator (A * B)
    numerator = sum([user_vector[x] * book_vector[x] for x in intersection])

    # Calculate the denominator (||A|| * ||B||)
    sum1 = sum([user_vector[x] ** 2 for x in user_vector.keys()])
    sum2 = sum([book_vector[x] ** 2 for x in book_vector.keys()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)

    if not denominator:
        return 0.0

    return float(numerator) / denominator


# 1. Set the environment variable for Google Cloud credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-keys.json"

# 2. Initialize the Firestore client
db = firestore.Client()

# Initialize the FastAPI application
app = FastAPI(title="Readar Backend")


# Define the Book model using Pydantic
class Book(BaseModel):
    google_book_id: str  # Unique Google Books ID to prevent duplicates
    title: str
    author: str
    genres: List[str] = []


# --- ENDPOINTS ---

# Root endpoint
@app.get("/")
def read_root():
    return {"message": "Welcome to the Readar backend!"}


# Search books using the Google Books API
@app.get("/search/{query}")
def search_books(query: str):
    # Prepare the URL to query Google Books
    url = f"https://www.googleapis.com/books/v1/volumes?q={query}"

    # Make the request to Google
    response = requests.get(url)
    data = response.json()

    # Extract only the useful information for the Android app
    results = []
    if "items" in data:
        for item in data["items"]:
            book_info = item.get("volumeInfo", {})
            results.append({
                "title": book_info.get("title", "Unknown Title"),
                "authors": book_info.get("authors", ["Unknown Author"]),
                "categories": book_info.get("categories", ["No category"]),
                "thumbnail": book_info.get("imageLinks", {}).get("thumbnail", "")
            })

    return {"query": query, "results": results}


# Save a book to a specific user's library
@app.post("/users/{user_id}/library/add")
def add_book_to_library(user_id: str, book: Book):
    # Path: users -> specific user -> library -> specific book
    doc_ref = db.collection("users").document(user_id).collection("library").document(book.google_book_id)

    doc_ref.set({
        "title": book.title,
        "author": book.author,
        "genres": book.genres,
        "status": "to_read",
        "added_at": datetime.now(timezone.utc)  # Save the exact UTC timestamp
    })

    return {"message": f"Book '{book.title}' successfully saved to {user_id}'s library!"}


# Get the complete library of a specific user
@app.get("/users/{user_id}/library")
def get_library(user_id: str):
    # Fetch all documents in the user's specific 'library' subcollection
    docs = db.collection("users").document(user_id).collection("library").stream()

    books = []
    for doc in docs:
        # Convert the document to a Python dictionary
        book_data = doc.to_dict()
        # Add the unique Firestore ID
        book_data["id"] = doc.id
        books.append(book_data)

    # Return the list to the Android app
    return {"library": books}


# Add or update a rating for an existing book in the user's library
@app.put("/users/{user_id}/library/{book_id}/rate")
def rate_book(user_id: str, book_id: str, rating: int):
    # Security check: rating must be between 1 and 5
    if rating < 1 or rating > 5:
        return {"error": "Rating must be a number between 1 and 5."}

    # Path to the specific book in the user's library
    doc_ref = db.collection("users").document(user_id).collection("library").document(book_id)

    # Use merge=True to update only the 'rating' field without overwriting the rest
    doc_ref.set({"rating": rating}, merge=True)

    return {"message": f"Feedback registered! You gave {rating} stars."}


# Generate personalized recommendations based on the user's favorite genres
@app.get("/users/{user_id}/recommendations/genres")
def get_genre_recommendations(user_id: str):
    # Retrieve the user's reading history (only rated books)
    rated_books = db.collection("users").document(user_id).collection("library").where("rating", ">", 0).stream()

    # Build the User Profile based ONLY on genres
    user_genres = {}
    for doc in rated_books:
        book = doc.to_dict()
        rating = book.get("rating", 0)
        for genre in book.get("genres", []):
            user_genres[genre] = user_genres.get(genre, 0) + rating

    if not user_genres:
        return {"message": "Rate some books to get genre-based recommendations!"}

    # Find the top 2 absolute favorite genres
    sorted_genres = sorted(user_genres.items(), key=lambda x: x[1], reverse=True)
    top_2_genres = [g[0] for g in sorted_genres[:2]]

    # Gather candidates from Google Books
    recommendations = []
    for genre in top_2_genres:
        url = f"https://www.googleapis.com/books/v1/volumes?q=subject:{genre}&orderBy=relevance&maxResults=15"
        res = requests.get(url).json()

        for item in res.get("items", []):
            book_info = item.get("volumeInfo", {})
            title = book_info.get("title", "Unknown Title")
            book_genres = book_info.get("categories", [])

            # Apply Cosine Similarity
            book_vector = {g: 1 for g in book_genres}
            similarity_score = calculate_cosine_similarity(user_genres, book_vector)

            if similarity_score > 0:
                recommendations.append({
                    "title": title,
                    "genres": book_genres,
                    "match_score": round(similarity_score * 100, 2)  # Affinity percentage
                })

    # Sort by best match and return top 10
    recommendations.sort(key=lambda x: x["match_score"], reverse=True)
    return {"based_on_genres": top_2_genres, "results": recommendations[:10]}


# Generate personalized recommendations based on the user's favorite author
@app.get("/users/{user_id}/recommendations/authors")
def get_author_recommendations(user_id: str):
    # Retrieve the user's reading history
    rated_books = db.collection("users").document(user_id).collection("library").where("rating", ">", 0).stream()

    # Build the User Profile based ONLY on authors
    user_authors = {}
    for doc in rated_books:
        book = doc.to_dict()
        author = book.get("author", "")
        rating = book.get("rating", 0)

        if author:
            # Save the maximum rating given to this author
            user_authors[author] = max(user_authors.get(author, 0), rating)

    if not user_authors:
        return {"message": "Rate some books to get author-based recommendations!"}

    # Find the absolute favorite author
    top_author = max(user_authors, key=user_authors.get)

    # If the highest rating for the top author is too low, don't recommend
    if user_authors[top_author] < 4:
        return {"message": "You don't have a highly rated favorite author yet."}

    # Search for other books by this author on Google
    url = f"https://www.googleapis.com/books/v1/volumes?q=inauthor:{top_author}&maxResults=10"
    res = requests.get(url).json()

    recommendations = []
    for item in res.get("items", []):
        book_info = item.get("volumeInfo", {})
        title = book_info.get("title", "Unknown Title")

        recommendations.append({
            "title": title,
            "author": top_author,
        })

    return {"based_on_author": top_author, "results": recommendations}


# Get trending books across ALL users (Collection Group Query)
@app.get("/trending")
def get_trending_books():
    # 1. Calculate the exact date 30 days ago
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # 2. Use a collection_group query to search in ALL 'library' subcollections!
    docs = db.collection_group("library").where("added_at", ">=", thirty_days_ago).stream()

    book_counts = {}
    book_details = {}

    # 3. Count occurrences across all users
    for doc in docs:
        book = doc.to_dict()
        title = book.get("title", "Unknown Title")

        if title in book_counts:
            book_counts[title] += 1
        else:
            book_counts[title] = 1
            book_details[title] = {
                "title": title,
                "author": book.get("author", "Unknown Author"),
                "genres": book.get("genres", [])
            }

    if not book_counts:
        return {"message": "No books added in the last month. Be the first to add one!"}

    # 4. Sort books from most popular to least popular
    sorted_trending = sorted(book_counts.items(), key=lambda x: x[1], reverse=True)

    trending_list = []

    # Build the top 10 leaderboard
    for title, count in sorted_trending[:10]:
        details = book_details[title]
        details["times_added"] = count
        trending_list.append(details)

    return {
        "section": "Trending (Last 30 Days)",
        "total_unique_books": len(book_counts),
        "books": trending_list
    }