import os
import math
import requests
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google.cloud import firestore
from typing import Optional


# --- API CONFIGURATION ---
# Loads from variables first, falls back to key
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "AIzaSyCZjo7ceLtmnudyWK9kcsv8p54JRzPdhIk")


# --- HELPER FUNCTIONS ---

# Calculate the cosine similarity between two vectors
def calculate_cosine_similarity(user_vector: dict, book_vector: dict):
    intersection = set(user_vector.keys()) & set(book_vector.keys())
    numerator = sum([user_vector[x] * book_vector[x] for x in intersection])
    sum1 = sum([user_vector[x] ** 2 for x in user_vector.keys()])
    sum2 = sum([book_vector[x] ** 2 for x in book_vector.keys()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)

    if not denominator:
        return 0.0
    return float(numerator) / denominator


# Standardize the book object structure across all endpoints
def extract_book_data(item: dict) -> dict:
    book_info = item.get("volumeInfo", {})

    authors_list = book_info.get("authors", ["Unknown Author"])
    primary_author = authors_list[0] if authors_list else "Unknown Author"

    return {
        "google_book_id": item.get("id", "Unknown ID"),
        "title": book_info.get("title", "Unknown Title"),
        "author": primary_author,
        "pageCount": book_info.get("pageCount", 0),
        "genres": book_info.get("categories", ["Unknown Genre"]),
        "thumbnail": book_info.get("imageLinks", {}).get("thumbnail", ""),
        "description": book_info.get("description", "No description available."),
        "publishedDate": book_info.get("publishedDate", "Unknown"),
        "rating": 0,          # Default for books not yet in library
        "status": "none"      # Default for books not yet in library
    }


# --- INITIALIZATION ---

# Set the variable for Google Cloud credentials if the file exists
key_path = "google-keys.json"
if os.path.exists(key_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path

db = firestore.Client()

app = FastAPI(title="Readar Backend")


# --- PYDANTIC MODELS ---

class StatusUpdate(BaseModel):
    status: str


class Book(BaseModel):
    google_book_id: str
    title: str
    author: str
    pageCount: int = 0
    genres: List[str] = []
    thumbnail: str = ""
    description: str = "No description available."
    publishedDate: str = "Unknown"
    rating: int = 0
    status: str = "none"


class UserProfile(BaseModel):
    name: str
    email: str
    profile_image: str = "https://via.placeholder.com/150" # Default image


class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    profile_image: Optional[str] = None

# --- ENDPOINTS ---

# Root
@app.get("/")
def read_root():
    return {"message": "Welcome to the Readar backend!"}


# Search books using the Google Books API
@app.get("/search/{query}")
def search_books(query: str):
    clean_query = query.lower().strip()


    url = f"https://www.googleapis.com/books/v1/volumes?q={clean_query}&langRestrict=en&key={GOOGLE_BOOKS_API_KEY}"
    response = requests.get(url)
    data = response.json()

    results = []
    if "items" in data:
        for item in data["items"]:
            results.append(extract_book_data(item))

    return {"query": clean_query, "results": results}


# Save a book to a specific user's library
@app.post("/users/{user_id}/library/add")
def add_book_to_library(user_id: str, book: Book):
    doc_ref = db.collection("users").document(user_id).collection("library").document(book.google_book_id)

    doc_ref.set({
        "title": book.title,
        "author": book.author,
        "pageCount": book.pageCount,
        "genres": book.genres,
        "thumbnail": book.thumbnail,
        "description": book.description,
        "publishedDate": book.publishedDate,
        "status": "to_read",
        "rating": 0,
        "added_at": datetime.now(timezone.utc)
    })

    return {"message": f"Book '{book.title}' successfully saved to {user_id}'s library!"}


# Get the complete library of a specific user
@app.get("/users/{user_id}/library")
def get_library(user_id: str):
    docs = db.collection("users").document(user_id).collection("library").stream()
    books = []
    for doc in docs:
        book_data = doc.to_dict()
        book_data["id"] = doc.id
        books.append(book_data)

    return {"library": books}


# Add or update a rating for an existing book in the user's library
@app.put("/users/{user_id}/library/{book_id}/rate")
def rate_book(user_id: str, book_id: str, rating: int):
    if rating < 1 or rating > 5:
        return {"error": "Rating must be a number between 1 and 5."}

    doc_ref = db.collection("users").document(user_id).collection("library").document(book_id)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Book not found in user library. Add it first.")

    doc_ref.set({"rating": rating}, merge=True)
    return {"message": f"Feedback registered! You gave {rating} stars."}


# Generate personalized recommendations based on the user's favorite genres
@app.get("/users/{user_id}/recommendations/genres")
def get_genre_recommendations(user_id: str):
    library_docs = list(db.collection("users").document(user_id).collection("library").stream())
    read_book_titles = {doc.to_dict().get("title") for doc in library_docs}

    user_genres = {}
    for doc in library_docs:
        book = doc.to_dict()
        rating = book.get("rating", 0)
        if rating > 0:
            for genre in book.get("genres", []):
                clean_genre = genre.lower().strip()
                user_genres[clean_genre] = user_genres.get(clean_genre, 0) + rating

    if not user_genres:
        return {"message": "Rate some books to get genre-based recommendations!"}

    sorted_genres = sorted(user_genres.items(), key=lambda x: x[1], reverse=True)
    top_2_genres = [g[0] for g in sorted_genres[:2]]

    recommendations = []
    fallback_recommendations = []

    for genre in top_2_genres:
        url = f"https://www.googleapis.com/books/v1/volumes?q=subject:{genre}&orderBy=relevance&maxResults=15&langRestrict=en&key={GOOGLE_BOOKS_API_KEY}"
        res = requests.get(url).json()

        for item in res.get("items", []):
            parsed_book = extract_book_data(item)

            if parsed_book["title"] in read_book_titles:
                continue

            book_vector = {g.lower().strip(): 1 for g in parsed_book["genres"]}
            similarity_score = calculate_cosine_similarity(user_genres, book_vector)

            parsed_book["match_score"] = round(similarity_score * 100, 2)

            if similarity_score > 0:
                recommendations.append(parsed_book)
            else:
                fallback_recommendations.append(parsed_book)

    recommendations.sort(key=lambda x: x["match_score"], reverse=True)

    if len(recommendations) < 10:
        needed = 10 - len(recommendations)
        recommendations.extend(fallback_recommendations[:needed])

    return {"based_on_genres": top_2_genres, "results": recommendations[:10]}


# Generate personalized recommendations based on the user's favorite author
@app.get("/users/{user_id}/recommendations/authors")
def get_author_recommendations(user_id: str):
    library_docs = list(db.collection("users").document(user_id).collection("library").stream())
    read_book_titles = {doc.to_dict().get("title") for doc in library_docs}

    user_authors = {}
    for doc in library_docs:
        book = doc.to_dict()
        author = book.get("author", "")
        rating = book.get("rating", 0)

        if author and rating > 0:
            clean_author = author.lower().strip()
            user_authors[clean_author] = max(user_authors.get(clean_author, 0), rating)

    if not user_authors:
        return {"message": "Rate some books to get author-based recommendations!"}

    top_author = max(user_authors, key=user_authors.get)

    if user_authors[top_author] < 4:
        return {"message": "You don't have a highly rated favorite author yet."}

    url = f"https://www.googleapis.com/books/v1/volumes?q=inauthor:{top_author}&maxResults=15&langRestrict=en&key={GOOGLE_BOOKS_API_KEY}"
    res = requests.get(url).json()

    recommendations = []
    for item in res.get("items", []):
        parsed_book = extract_book_data(item)

        if parsed_book["title"] in read_book_titles:
            continue

        recommendations.append(parsed_book)

    return {"based_on_author": top_author.title(), "results": recommendations[:10]}


# Get trending books across ALL users (Collection Group Query)
@app.get("/trending")
def get_trending_books():
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    docs = db.collection_group("library").where("added_at", ">=", thirty_days_ago).stream()

    book_counts = {}
    book_details = {}

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
                "genres": book.get("genres", []),
                "pageCount": book.get("pageCount", 0),
                "thumbnail": book.get("thumbnail", ""),
                "description": book.get("description", "No description available."),
                "publishedDate": book.get("publishedDate", "Unknown"),
                "rating": book.get("rating", 0),
                "status": book.get("status", "none")
            }

    if not book_counts:
        return {"message": "No books added in the last month. Be the first to add one!"}

    sorted_trending = sorted(book_counts.items(), key=lambda x: x[1], reverse=True)

    trending_list = []
    for title, count in sorted_trending[:10]:
        details = book_details[title]
        details["times_added"] = count
        trending_list.append(details)

    return {
        "section": "Trending (Last 30 Days)",
        "total_unique_books": len(book_counts),
        "books": trending_list
    }


# Get a specific book from the user's library
@app.get("/users/{user_id}/library/{book_id}")
def get_book_from_library(user_id: str, book_id: str):
    doc_ref = db.collection("users").document(user_id).collection("library").document(book_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Book not found in user library.")

    book_data = doc.to_dict()
    book_data["id"] = doc.id
    return book_data


# Update the reading status of a specific book
@app.patch("/users/{user_id}/library/{book_id}/status")
def update_book_status(user_id: str, book_id: str, status_update: StatusUpdate):
    clean_status = status_update.status.lower().strip()
    valid_statuses = ["to_read", "reading", "read"]

    if clean_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    doc_ref = db.collection("users").document(user_id).collection("library").document(book_id)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Book not found in user library.")

    doc_ref.update({"status": clean_status})
    return {"message": f"Book status updated to '{clean_status}'."}


# Remove a book from the user's library
@app.delete("/users/{user_id}/library/{book_id}")
def remove_book_from_library(user_id: str, book_id: str):
    doc_ref = db.collection("users").document(user_id).collection("library").document(book_id)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Book not found in user library.")

    doc_ref.delete()
    return {"message": "Book successfully removed from your library."}


# Get detailed information for a specific book from Google Books API
@app.get("/books/{google_book_id}")
def get_book_details(google_book_id: str):
    url = f"https://www.googleapis.com/books/v1/volumes/{google_book_id}?key={GOOGLE_BOOKS_API_KEY}"
    response = requests.get(url)

    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Book not found in Google Books API.")

    data = response.json()

    return extract_book_data(data)


# Get similar book recommendations based on a specific book in the user's library
@app.get("/users/{user_id}/recommendations/similar/{book_id}")
def get_similar_books(user_id: str, book_id: str):
    doc_ref = db.collection("users").document(user_id).collection("library").document(book_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Book not found in user library.")

    target_book = doc.to_dict()
    target_title = target_book.get("title", "")
    target_genres = target_book.get("genres", [])

    if not target_genres:
        return {"message": "Cannot find similar books because the target book has no genres listed."}

    library_docs = list(db.collection("users").document(user_id).collection("library").stream())
    read_book_titles = {d.to_dict().get("title") for d in library_docs}

    main_genre = target_genres[0]
    url = f"https://www.googleapis.com/books/v1/volumes?q=subject:{main_genre}&orderBy=relevance&maxResults=15&langRestrict=en&key={GOOGLE_BOOKS_API_KEY}"
    response = requests.get(url)
    data = response.json()

    recommendations = []
    for item in data.get("items", []):
        parsed_book = extract_book_data(item)

        if parsed_book["title"] in read_book_titles or parsed_book["title"] == target_title:
            continue

        recommendations.append(parsed_book)

    return {
        "based_on_book": target_title,
        "results": recommendations[:5]
    }


# Generate personalized recommendations for a specific requested genre
@app.get("/users/{user_id}/recommendations/genre/{genre}")
def get_specific_genre_recommendations(user_id: str, genre: str):
    clean_genre = genre.lower().strip()

    library_docs = list(db.collection("users").document(user_id).collection("library").stream())
    read_book_titles = {doc.to_dict().get("title") for doc in library_docs}

    user_genres = {}
    for doc in library_docs:
        book = doc.to_dict()
        rating = book.get("rating", 0)
        if rating > 0:
            for g in book.get("genres", []):
                clean_g = g.lower().strip()
                user_genres[clean_g] = user_genres.get(clean_g, 0) + rating

    if not user_genres:
        return {"message": "Rate some books to get personalized genre recommendations!"}

    recommendations = []
    fallback_recommendations = []

    url = f"https://www.googleapis.com/books/v1/volumes?q=subject:{clean_genre}&orderBy=relevance&maxResults=15&langRestrict=en&key={GOOGLE_BOOKS_API_KEY}"
    res = requests.get(url).json()

    for item in res.get("items", []):
        parsed_book = extract_book_data(item)

        if parsed_book["title"] in read_book_titles:
            continue

        book_vector = {g.lower().strip(): 1 for g in parsed_book["genres"]}
        similarity_score = calculate_cosine_similarity(user_genres, book_vector)

        parsed_book["match_score"] = round(similarity_score * 100, 2)

        if similarity_score > 0:
            recommendations.append(parsed_book)
        else:
            fallback_recommendations.append(parsed_book)

    recommendations.sort(key=lambda x: x["match_score"], reverse=True)

    if len(recommendations) < 10:
        needed = 10 - len(recommendations)
        recommendations.extend(fallback_recommendations[:needed])

    return {"target_genre": genre, "results": recommendations[:10]}


# Generate personalized recommendations for a specific requested author
@app.get("/users/{user_id}/recommendations/author/{author}")
def get_specific_author_recommendations(user_id: str, author: str):
    clean_author = author.lower().strip()

    library_docs = list(db.collection("users").document(user_id).collection("library").stream())
    read_book_titles = {doc.to_dict().get("title") for doc in library_docs}

    user_genres = {}
    for doc in library_docs:
        book = doc.to_dict()
        rating = book.get("rating", 0)
        if rating > 0:
            for g in book.get("genres", []):
                clean_g = g.lower().strip()
                user_genres[clean_g] = user_genres.get(clean_g, 0) + rating

    if not user_genres:
        return {"message": "Rate some books to get personalized author recommendations!"}

    recommendations = []
    fallback_recommendations = []

    url = f"https://www.googleapis.com/books/v1/volumes?q=inauthor:{clean_author}&orderBy=relevance&maxResults=15&langRestrict=en&key={GOOGLE_BOOKS_API_KEY}"
    res = requests.get(url).json()

    for item in res.get("items", []):
        parsed_book = extract_book_data(item)

        if parsed_book["title"] in read_book_titles:
            continue

        book_vector = {g.lower().strip(): 1 for g in parsed_book["genres"]}
        similarity_score = calculate_cosine_similarity(user_genres, book_vector)

        parsed_book["match_score"] = round(similarity_score * 100, 2)

        if similarity_score > 0:
            recommendations.append(parsed_book)
        else:
            fallback_recommendations.append(parsed_book)

    recommendations.sort(key=lambda x: x["match_score"], reverse=True)

    if len(recommendations) < 10:
        needed = 10 - len(recommendations)
        recommendations.extend(fallback_recommendations[:needed])

    return {"target_author": author.title(), "results": recommendations[:10]}


# Create or update a user profile
@app.post("/users/{user_id}/profile")
def create_user_profile(user_id: str, profile: UserProfile):
    doc_ref = db.collection("users").document(user_id)

    doc_ref.set({
        "user_id": user_id,
        "name": profile.name,
        "email": profile.email,
        "profile_image": profile.profile_image,
        "created_at": datetime.now(timezone.utc)
    }, merge=True)

    return {"message": f"Profile for {profile.name} successfully created/updated."}


# Get a user's profile information
@app.get("/users/{user_id}/profile")
def get_user_profile(user_id: str):
    doc_ref = db.collection("users").document(user_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")

    profile_data = doc.to_dict()
    return profile_data


# Update specific fields of a user's profile
@app.patch("/users/{user_id}/profile")
def update_user_profile(user_id: str, update_data: UserProfileUpdate):
    doc_ref = db.collection("users").document(user_id)

    # Verify the user actually exists
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="User profile not found.")


    update_dict = {key: value for key, value in update_data.model_dump().items() if value is not None}

    if not update_dict:
        raise HTTPException(status_code=400, detail="No valid fields provided for update.")


    doc_ref.update(update_dict)

    return {"message": "Profile successfully updated.", "updated_fields": list(update_dict.keys())}