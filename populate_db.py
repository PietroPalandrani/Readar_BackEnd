import os
import time
import requests
from datetime import datetime, timezone
from google.cloud import firestore

# 1. Configuration and Database Connection
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-keys.json"
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "AIzaSyCZjo7ceLtmnudyWK9kcsv8p54JRzPdhIk")
db = firestore.Client()

# 2. User Profiles Data
dummy_profiles = {
    "lorenzo_test": {
        "name": "Lorenzo",
        "email": "lorenzo@example.com",
        "profile_image": "https://via.placeholder.com/150.png?text=Lorenzo"
    },
    "pietro_test": {
        "name": "Pietro",
        "email": "pietro@example.com",
        "profile_image": "https://via.placeholder.com/150.png?text=Pietro"
    },
    "celia_test": {
        "name": "Celia",
        "email": "celia@example.com",
        "profile_image": "https://via.placeholder.com/150.png?text=Celia"
    }
}

# 3. Target Dataset (Removed the fake IDs, added just title, author, genres, rating)
dummy_data = [
    # --- LORENZO'S LIBRARY ---
    {"user": "lorenzo_test", "title": "A Brief History of Time", "author": "Stephen Hawking", "genres": ["Science"],
     "rating": 5},
    {"user": "lorenzo_test", "title": "Cosmos", "author": "Carl Sagan", "genres": ["Science"], "rating": 5},
    {"user": "lorenzo_test", "title": "The Pragmatic Programmer", "author": "Andrew Hunt", "genres": ["Computers"],
     "rating": 4},
    {"user": "lorenzo_test", "title": "Clean Code", "author": "Robert C. Martin", "genres": ["Computers"], "rating": 5},

    # --- PIETRO'S LIBRARY ---
    {"user": "pietro_test", "title": "In Cold Blood", "author": "Truman Capote", "genres": ["True Crime"], "rating": 5},
    {"user": "pietro_test", "title": "I'll Be Gone in the Dark", "author": "Michelle McNamara",
     "genres": ["True Crime"], "rating": 4},
    {"user": "pietro_test", "title": "Meditations", "author": "Marcus Aurelius", "genres": ["Philosophy"], "rating": 5},
    {"user": "pietro_test", "title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "genres": ["Psychology"],
     "rating": 5},

    # --- CELIA'S LIBRARY ---
    {"user": "celia_test", "title": "Pride and Prejudice", "author": "Jane Austen", "genres": ["Fiction"], "rating": 5},
    {"user": "celia_test", "title": "The Lord of the Rings", "author": "J.R.R. Tolkien", "genres": ["Fiction"],
     "rating": 5},
    {"user": "celia_test", "title": "Mastering the Art of French Cooking", "author": "Julia Child",
     "genres": ["Cooking"], "rating": 5},
    {"user": "celia_test", "title": "The Story of Art", "author": "E.H. Gombrich", "genres": ["Art"], "rating": 4}
]


# Note: I shortened the list to 12 books to keep the code block concise.
# You can paste the rest of your books directly into this list following the exact same format.

def fetch_real_google_book_data(title: str, author: str):
    """Fetches real ID and metadata from Google Books API."""
    query = f"intitle:{title}+inauthor:{author}"
    url = f"https://www.googleapis.com/books/v1/volumes?q={query}&langRestrict=en&key={GOOGLE_BOOKS_API_KEY}"

    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if "items" in data and len(data["items"]) > 0:
            # Get the top search result
            item = data["items"][0]
            vol = item.get("volumeInfo", {})
            return {
                "google_book_id": item.get("id"),
                "pageCount": vol.get("pageCount", 0),
                "thumbnail": vol.get("imageLinks", {}).get("thumbnail", ""),
                "description": vol.get("description", "No description available."),
                "publishedDate": vol.get("publishedDate", "Unknown")
            }
    return None


print("Starting database population...")

# 4. Create User Profile Documents
print("\n--- Creating User Profiles ---")
for user_id, profile in dummy_profiles.items():
    user_ref = db.collection("users").document(user_id)
    user_ref.set({
        "user_id": user_id,
        "name": profile["name"],
        "email": profile["email"],
        "profile_image": profile["profile_image"],
        "created_at": datetime.now(timezone.utc)
    }, merge=True)
    print(f"Created profile for {profile['name']} ({user_id})")

# 5. Populate Libraries with Real API Data
print(f"\n--- Fetching Real Data and Adding {len(dummy_data)} Books ---")
for count, data in enumerate(dummy_data, 1):
    print(f"[{count}/{len(dummy_data)}] Fetching data for: '{data['title']}'...")

    real_data = fetch_real_google_book_data(data["title"], data["author"])

    if real_data and real_data["google_book_id"]:
        # Use the real Google Book ID as the Firestore document name
        doc_ref = db.collection("users").document(data["user"]).collection("library").document(
            real_data["google_book_id"])

        doc_ref.set({
            "title": data["title"],
            "author": data["author"],
            "genres": data["genres"],
            "rating": data["rating"],
            "pageCount": real_data["pageCount"],
            "thumbnail": real_data["thumbnail"],
            "description": real_data["description"],
            "publishedDate": real_data["publishedDate"],
            "status": "read",
            "added_at": datetime.now(timezone.utc)
        })
        print(f"   -> Saved with real ID: {real_data['google_book_id']}")
    else:
        print(f"   -> FAILED: Could not find '{data['title']}' in Google Books API.")

    # Adding a small delay to avoid hitting rate limits by making requests too fast
    time.sleep(0.5)

print("\nDatabase successfully populated with real Google Books data!")