import os
import math
import httpx
import logging
import asyncio
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Depends, Security, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient
import firebase_admin
from firebase_admin import auth

# ---------------------------------------------------------------------------
# LOGGING SETUP
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ENVIRONMENT & CONFIGURATION
# ---------------------------------------------------------------------------
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY")
GOOGLE_BOOKS_BASE_URL = "https://www.googleapis.com/books/v1/volumes"

if not GOOGLE_BOOKS_API_KEY:
    logger.warning("GOOGLE_BOOKS_API_KEY is not set. Book searches will fail.")

# ---------------------------------------------------------------------------
# CACHES
# ---------------------------------------------------------------------------
# TTLCache handles both expiry and bounded size (LRU eviction when full).

# Google Books API results: 500 entries max, 12-hour TTL
_google_api_cache: TTLCache = TTLCache(maxsize=500, ttl=60 * 60 * 12)
_google_cache_lock = asyncio.Lock()

# Trending books: 1 entry max, 10-minute TTL
_trending_cache: TTLCache = TTLCache(maxsize=1, ttl=60 * 10)
_trending_cache_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# FIREBASE / FIRESTORE INITIALIZATION
# ---------------------------------------------------------------------------
key_path = "google-keys.json"
if os.path.exists(key_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path

try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()

# Async client for use inside async endpoints (non-blocking)
# Sync client kept for sync endpoints (FastAPI runs those in a thread pool)
db = firestore.Client()
async_db = AsyncClient()


# ---------------------------------------------------------------------------
# APP LIFECYCLE AND MIDDLEWARE
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    fastapi_app.state.http_client = httpx.AsyncClient(timeout=10.0)
    yield
    await fastapi_app.state.http_client.aclose()
    await async_db.close()


middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["https://readar-backend-561616357714.europe-southwest1.run.app"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = FastAPI(
    title="Readar API",
    description="Backend API for the Readar Android app — handles book discovery, library management, and personalized recommendations.",
    version="1.0.0",
    lifespan=lifespan,
    middleware=middleware,
)


# ---------------------------------------------------------------------------
# GLOBAL EXCEPTION HANDLER
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catches any unexpected server errors, logs the trace, and returns a clean 500 response."""
    logger.error(
        "Unhandled exception on %s %s\n%s",
        request.method, request.url, traceback.format_exc(),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


# ---------------------------------------------------------------------------
# SECURITY & AUTHENTICATION
# ---------------------------------------------------------------------------
security = HTTPBearer()


async def get_current_uid(
        credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """Verifies the Firebase JWT token provided by the client and extracts the user's UID."""
    try:
        decoded = auth.verify_id_token(credentials.credentials)
        return decoded["uid"]
    except Exception as exc:
        logger.warning("Token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")


# ---------------------------------------------------------------------------
# INPUT VALIDATION
# ---------------------------------------------------------------------------
def require_non_empty_id(value: str, name: str = "ID") -> str:
    """Raises 400 immediately if a path parameter is empty or blank."""
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail=f"{name} cannot be empty.")
    return value.strip()


# ---------------------------------------------------------------------------
# REQUEST MODELS (Incoming Data)
# ---------------------------------------------------------------------------
class StatusUpdate(BaseModel):
    status: str = Field(..., examples=["reading"], description="One of: reading, read")


class BookRequest(BaseModel):
    """Payload sent by the client when adding a new book to their library."""
    id: str
    title: str
    author: str
    pageCount: int = Field(default=0, ge=0)
    genres: List[str] = []
    thumbnail: str = ""
    description: str = "No description available."
    publishedDate: str = "Unknown"
    rating: int = Field(default=0, ge=0, le=5)
    status: str = "none"


class UserProfileRequest(BaseModel):
    name: str
    email: str
    profile_image: str = Field(default="https://via.placeholder.com/150")


class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    profile_image: Optional[str] = None


# ---------------------------------------------------------------------------
# RESPONSE MODELS (Outgoing Data)
# ---------------------------------------------------------------------------
class BookResponse(BaseModel):
    """A standardized book format returned by search and recommendation endpoints."""
    id: str
    title: str
    author: str
    pageCount: int = 0
    genres: List[str] = []
    thumbnail: str = ""
    description: str = "No description available."
    publishedDate: str = "Unknown"
    rating: int = 0
    status: str = "none"
    match_score: Optional[float] = None
    times_added: Optional[int] = None
    added_at: Optional[datetime] = None


class LibraryBookResponse(BookResponse):
    """A book that lives in the user's library. Guarantees an ID is present."""
    id: str


class MessageResponse(BaseModel):
    message: str


class UserProfileResponse(BaseModel):
    user_id: str
    name: str
    email: str
    profile_image: str
    created_at: datetime


class ProfileUpdatedResponse(BaseModel):
    message: str
    updated_fields: List[str]


class RatingResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# CORE ALGORITHMS & HELPERS
# ---------------------------------------------------------------------------
def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Calculates the mathematical similarity between two vectors (e.g., user tastes vs book genres)."""
    common_keys = vec_a.keys() & vec_b.keys()
    numerator = sum(vec_a[k] * vec_b[k] for k in common_keys)
    denom = math.sqrt(sum(v ** 2 for v in vec_a.values())) * math.sqrt(
        sum(v ** 2 for v in vec_b.values())
    )
    return numerator / denom if denom else 0.0


def extract_book_data(item: dict) -> dict:
    """
    Safely extracts and formats nested book data coming from the Google Books API.
    All genres are extracted (not just the first) to improve recommendation accuracy.
    """
    info = item.get("volumeInfo", {})

    raw_authors = info.get("authors")
    main_author = raw_authors[0] if raw_authors else "Unknown Author"

    # Extract and clean ALL genres, not just the first one.
    # Google often provides nested genres like "Fiction / Thriller" — we split and keep both.
    raw_categories = info.get("categories") or []
    genres: list[str] = []
    for category in raw_categories:
        for part in category.split("/"):
            clean = part.strip()
            if clean and clean not in genres:
                genres.append(clean)
    if not genres:
        genres = ["Unknown Genre"]

    image_links = info.get("imageLinks") or {}

    return {
        "id": item.get("id") or "",
        "title": info.get("title") or "Unknown Title",
        "author": main_author,
        "pageCount": info.get("pageCount") or 0,
        "genres": genres,
        "thumbnail": image_links.get("thumbnail") or "",
        "description": info.get("description") or "No description available.",
        "publishedDate": info.get("publishedDate") or "Unknown",
        "rating": 0,
        "status": "none",
        "added_at": None,
    }


# Shared retry configuration for all Google Books API calls
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


async def _retry_backoff(attempt: int) -> None:
    """Exponential backoff: waits 1s after attempt 1, 2s after attempt 2."""
    await asyncio.sleep(2 ** (attempt - 1))


async def google_books_search(client: httpx.AsyncClient, params: dict) -> list[dict]:
    """
    Queries the Google Books API to search for volumes.
    Results are cached by TTLCache — same query within 12h returns instantly.
    Cache writes are protected by a lock to prevent race conditions.
    """
    cache_key = tuple(sorted(params.items()))

    if cache_key in _google_api_cache:
        logger.info("Cache hit for Google Books search: %s", params.get("q"))
        return _google_api_cache[cache_key]

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await client.get(
                GOOGLE_BOOKS_BASE_URL,
                params={**params, "key": GOOGLE_BOOKS_API_KEY, "langRestrict": "en"},
            )

            if response.status_code == 200:
                items = response.json().get("items", [])
                async with _google_cache_lock:
                    _google_api_cache[cache_key] = items
                return items

            if response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS:
                logger.warning("Google Books %s — retrying in %ss (attempt %s/%s)...",
                               response.status_code, 2 ** (attempt - 1), attempt, _MAX_ATTEMPTS)
                await _retry_backoff(attempt)
                continue

            logger.error("Google Books failed with status %s for params %s.", response.status_code, params)
            return []

        except httpx.RequestError as exc:
            logger.error("Google Books network error (attempt %s/%s): %s", attempt, _MAX_ATTEMPTS, exc)
            if attempt < _MAX_ATTEMPTS:
                await _retry_backoff(attempt)
                continue
            return []
        except Exception as exc:
            logger.error("Unexpected error during Google Books search: %s", exc)
            return []

    return []


async def google_books_fetch(client: httpx.AsyncClient, book_id: str) -> dict | None:
    """
    Fetches the full details of a single book by its exact ID.
    Results are cached by TTLCache — same book_id within 12h returns instantly.
    Cache writes are protected by a lock to prevent race conditions.
    """
    if book_id in _google_api_cache:
        logger.info("Cache hit for Google Books fetch: %s", book_id)
        return _google_api_cache[book_id]

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await client.get(
                f"{GOOGLE_BOOKS_BASE_URL}/{book_id}",
                params={"key": GOOGLE_BOOKS_API_KEY},
            )

            if response.status_code == 200:
                data = response.json()
                async with _google_cache_lock:
                    _google_api_cache[book_id] = data
                return data

            if response.status_code == 404:
                return None

            if response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS:
                logger.warning("Google Books %s on book_id=%s — retrying in %ss (attempt %s/%s)...",
                               response.status_code, book_id, 2 ** (attempt - 1), attempt, _MAX_ATTEMPTS)
                await _retry_backoff(attempt)
                continue

            logger.error("Google Books returned %s for book_id=%s", response.status_code, book_id)
            raise HTTPException(status_code=502, detail="Google Books API error.")

        except HTTPException:
            raise
        except httpx.RequestError as exc:
            logger.error("Network error fetching book (attempt %s/%s): %s", attempt, _MAX_ATTEMPTS, exc)
            if attempt < _MAX_ATTEMPTS:
                await _retry_backoff(attempt)
                continue
            raise HTTPException(status_code=503, detail="Could not reach Google Books API.")

    raise HTTPException(status_code=503, detail="Google Books temporarily unavailable.")


def build_user_genre_vector(library_docs) -> dict[str, float]:
    """
    Builds a 'taste profile' vector for the user based on their highly-rated books.
    All genres of a book contribute to the vector, weighted by the book's rating.
    Example result: {"fantasy": 9.0, "fiction": 5.0, "thriller": 4.0}
    """
    genres: dict[str, float] = {}
    for doc in library_docs:
        book = doc.to_dict()
        rating = book.get("rating", 0)
        if rating > 0:
            for g in book.get("genres", []):
                key = g.lower().strip()
                genres[key] = genres.get(key, 0) + rating
    return genres


def score_and_rank(
        items: list[dict],
        user_genre_vector: dict[str, float],
        excluded_titles: set[str],
        *,
        limit: int = 10,
) -> list[dict]:
    """
    The core recommendation engine. Scores a batch of books and returns the top matches.
    Score = 80% genre similarity + 20% popularity (capped at 10k ratings).
    Books with zero genre overlap are kept as fallback to avoid empty responses.
    """
    matched: list[dict] = []
    fallback: list[dict] = []

    for item in items:
        book = extract_book_data(item)

        if book["title"] in excluded_titles:
            continue

        # Build the book's genre vector from all its genres
        book_vector: dict[str, float] = {g.lower().strip(): 1.0 for g in book["genres"]}
        similarity = cosine_similarity(user_genre_vector, book_vector)

        raw_count = item.get("volumeInfo", {}).get("ratingsCount", 0) or 0
        popularity = min(raw_count / 10000, 1.0)

        book["match_score"] = round((similarity * 0.8 + popularity * 0.2) * 100, 2)

        (matched if similarity > 0 else fallback).append(book)

    matched.sort(key=lambda b: b["match_score"], reverse=True)

    if len(matched) < limit:
        matched.extend(fallback[: limit - len(matched)])

    return matched[:limit]


def get_read_titles(library_docs) -> set[str]:
    """Extracts a set of all titles currently in the user's library."""
    return {doc.to_dict().get("title", "") for doc in library_docs}


def _library_doc_sync(uid: str, book_id: str):
    """Sync Firestore reference — for use inside sync (def) endpoints."""
    return db.collection("users").document(uid).collection("library").document(book_id)


def _library_doc_async(uid: str, book_id: str):
    """Async Firestore reference — for use inside async (async def) endpoints."""
    return async_db.collection("users").document(uid).collection("library").document(book_id)


async def _genre_recommendations(
        client: httpx.AsyncClient,
        user_genre_vector: dict[str, float],
        excluded_titles: set[str],
        genre: str,
        limit: int = 10,
) -> list[dict]:
    """Fetches books by a specific genre and ranks them against the user's taste."""
    items = await google_books_search(client, {"q": f"subject:{genre}", "maxResults": 30})
    return score_and_rank(items, user_genre_vector, excluded_titles, limit=limit)


async def _author_recommendations(
        client: httpx.AsyncClient,
        user_genre_vector: dict[str, float],
        excluded_titles: set[str],
        author: str,
        limit: int = 10,
) -> list[dict]:
    """Fetches books by a specific author and ranks them against the user's taste."""
    items = await google_books_search(client, {"q": f"inauthor:{author}", "maxResults": 30})
    return score_and_rank(items, user_genre_vector, excluded_titles, limit=limit)


# A standard taste profile used for brand-new users who haven't rated anything yet
DEFAULT_GENRE_VECTOR: dict[str, float] = {
    "fiction": 1.0,
    "mystery": 1.0,
    "fantasy": 1.0,
}


# ---------------------------------------------------------------------------
# PUBLIC ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/", response_model=MessageResponse, tags=["General"], summary="Health check")
def read_root():
    return MessageResponse(message="Welcome to the Readar API!")


@app.get(
    "/search/{query}",
    response_model=List[BookResponse],
    tags=["Search"],
    summary="Search books",
    description="Search the Google Books catalogue. Returns up to 30 results.",
)
async def search_books(query: str):
    require_non_empty_id(query, "Query")
    client: httpx.AsyncClient = app.state.http_client
    items = await google_books_search(client, {"q": query.lower().strip(), "maxResults": 30})
    return [extract_book_data(i) for i in items]


@app.get(
    "/trending",
    response_model=List[BookResponse],
    tags=["Search"],
    summary="Trending books",
    description="Returns the 10 most-added books across all users in the last 30 days. Cached for 10 minutes.",
)
async def get_trending_books():
    async with _trending_cache_lock:
        if "result" in _trending_cache:
            logger.info("Serving trending books from cache.")
            return _trending_cache["result"]

    since = datetime.now(timezone.utc) - timedelta(days=30)
    docs = async_db.collection_group("library").where("added_at", ">=", since).stream()

    counts: dict[str, int] = {}
    details: dict[str, dict] = {}

    async for doc in docs:
        book = doc.to_dict()
        title = book.get("title") or "Unknown Title"
        counts[title] = counts.get(title, 0) + 1
        if title not in details:
            filtered_book = {k: v for k, v in book.items() if v is not None}
            details[title] = filtered_book
            details[title]["id"] = book.get("id", doc.id)

    if not counts:
        return []

    books = [
        {**details[t], "times_added": c}
        for t, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    async with _trending_cache_lock:
        _trending_cache["result"] = books

    return books


@app.get(
    "/books/{book_id}",
    response_model=BookResponse,
    tags=["Search"],
    summary="Get book details",
    description="Fetch full details for a specific book directly from Google Books.",
)
async def get_book_details(book_id: str):
    require_non_empty_id(book_id, "Book ID")
    client: httpx.AsyncClient = app.state.http_client
    data = await google_books_fetch(client, book_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Book not found in Google Books API.")
    return extract_book_data(data)


# ---------------------------------------------------------------------------
# PROFILE ENDPOINTS
# ---------------------------------------------------------------------------
@app.post(
    "/profile",
    response_model=MessageResponse,
    status_code=201,
    tags=["Profile"],
    summary="Create or update profile",
)
def create_user_profile(profile: UserProfileRequest, uid: str = Depends(get_current_uid)):
    # merge=True so this is safe to call on both create and update
    db.collection("users").document(uid).set(
        {
            "user_id": uid,
            "name": profile.name,
            "email": profile.email,
            "profile_image": profile.profile_image,
            "created_at": datetime.now(timezone.utc),
        },
        merge=True,
    )
    return MessageResponse(message=f"Profile for {profile.name} successfully created/updated.")


@app.get(
    "/profile",
    response_model=UserProfileResponse,
    tags=["Profile"],
    summary="Get profile",
)
def get_user_profile(uid: str = Depends(get_current_uid)):
    doc = db.collection("users").document(uid).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    return doc.to_dict()


@app.patch(
    "/profile",
    response_model=ProfileUpdatedResponse,
    tags=["Profile"],
    summary="Update profile fields",
)
def update_user_profile(update_data: UserProfileUpdate, uid: str = Depends(get_current_uid)):
    doc_ref = db.collection("users").document(uid)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="User profile not found.")

    payload = {k: v for k, v in update_data.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="No valid fields provided for update.")

    doc_ref.update(payload)
    return ProfileUpdatedResponse(message="Profile updated.", updated_fields=list(payload.keys()))


# ---------------------------------------------------------------------------
# LIBRARY ENDPOINTS
# ---------------------------------------------------------------------------
@app.post(
    "/library/add",
    response_model=MessageResponse,
    status_code=201,
    tags=["Library"],
    summary="Add book to library",
)
def add_book_to_library(book: BookRequest, uid: str = Depends(get_current_uid)):
    _library_doc_sync(uid, book.id).set(
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "pageCount": book.pageCount,
            "genres": book.genres,
            "thumbnail": book.thumbnail,
            "description": book.description,
            "publishedDate": book.publishedDate,
            "status": "reading",
            "rating": 0,
            "added_at": datetime.now(timezone.utc),
        }
    )
    return MessageResponse(message=f"'{book.title}' added to your library.")


@app.get(
    "/library",
    response_model=List[LibraryBookResponse],
    tags=["Library"],
    summary="Get full library",
    description="Returns all books saved in the authenticated user's library.",
)
async def get_library(uid: str = Depends(get_current_uid)):
    docs = async_db.collection("users").document(uid).collection("library").stream()
    return [{**doc.to_dict(), "id": doc.id} async for doc in docs]


@app.get(
    "/library/latest",
    response_model=LibraryBookResponse,
    tags=["Library"],
    summary="Get the latest added book",
    description="Returns the most recently added book in the authenticated user's library.",
)
async def get_latest_library_book(uid: str = Depends(get_current_uid)):
    docs = (
        async_db.collection("users")
        .document(uid)
        .collection("library")
        .order_by("added_at", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    async for doc in docs:
        return {**doc.to_dict(), "id": doc.id}

    raise HTTPException(status_code=404, detail="Your library is empty.")


@app.get(
    "/library/{book_id}",
    response_model=LibraryBookResponse,
    tags=["Library"],
    summary="Get a single library book",
)
async def get_book_from_library(book_id: str, uid: str = Depends(get_current_uid)):
    require_non_empty_id(book_id, "Book ID")
    doc = await _library_doc_async(uid, book_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Book not found in library.")
    return {**doc.to_dict(), "id": doc.id}


@app.put(
    "/library/{book_id}/rate",
    response_model=RatingResponse,
    tags=["Library"],
    summary="Rate a book",
    description="Set a rating (1-5 stars) for a book already in the library.",
)
async def rate_book(
        book_id: str,
        rating: int = Query(..., ge=1, le=5, description="Star rating between 1 and 5"),
        uid: str = Depends(get_current_uid),
):
    require_non_empty_id(book_id, "Book ID")
    doc_ref = _library_doc_async(uid, book_id)
    if not (await doc_ref.get()).exists:
        raise HTTPException(status_code=404, detail="Book not found in library.")
    await doc_ref.set({"rating": rating}, merge=True)
    return RatingResponse(message=f"Rated {rating} star{'s' if rating > 1 else ''}.")


@app.patch(
    "/library/{book_id}/status",
    response_model=MessageResponse,
    tags=["Library"],
    summary="Update reading status",
    description="Update the reading status. Accepted values: `reading`, `read`.",
)
async def update_book_status(
        book_id: str,
        status_update: StatusUpdate,
        uid: str = Depends(get_current_uid),
):
    require_non_empty_id(book_id, "Book ID")
    valid = {"reading", "read"}
    clean = status_update.status.lower().strip()
    if clean not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {sorted(valid)}")

    doc_ref = _library_doc_async(uid, book_id)
    if not (await doc_ref.get()).exists:
        raise HTTPException(status_code=404, detail="Book not found in library.")

    await doc_ref.update({"status": clean})
    return MessageResponse(message=f"Status updated to '{clean}'.")


@app.delete(
    "/library/{book_id}",
    response_model=MessageResponse,
    tags=["Library"],
    summary="Remove book from library",
)
async def remove_book_from_library(book_id: str, uid: str = Depends(get_current_uid)):
    require_non_empty_id(book_id, "Book ID")
    doc_ref = _library_doc_async(uid, book_id)
    if not (await doc_ref.get()).exists:
        raise HTTPException(status_code=404, detail="Book not found in library.")
    await doc_ref.delete()
    return MessageResponse(message="Book removed from your library.")


# ---------------------------------------------------------------------------
# RECOMMENDATION ENDPOINTS
# ---------------------------------------------------------------------------
@app.get(
    "/recommendations/genres",
    response_model=List[BookResponse],
    tags=["Recommendations"],
    summary="Recommend by top genres",
    description="Returns up to 10 books based on the user's two highest-scored genres. Falls back to popular Fiction/Mystery/Fantasy for new users.",
)
async def get_genre_recommendations(uid: str = Depends(get_current_uid)):
    library_docs = [doc async for doc in async_db.collection("users").document(uid).collection("library").stream()]
    user_genre_vector = build_user_genre_vector(library_docs)
    excluded = get_read_titles(library_docs)
    client: httpx.AsyncClient = app.state.http_client

    if not user_genre_vector:
        genre_vector = DEFAULT_GENRE_VECTOR
        top_genres = list(DEFAULT_GENRE_VECTOR.keys())
    else:
        genre_vector = user_genre_vector
        top_genres = [g for g, _ in sorted(genre_vector.items(), key=lambda x: x[1], reverse=True)[:2]]

    all_results: list[dict] = []
    for genre in top_genres:
        all_results.extend(await _genre_recommendations(client, genre_vector, excluded, genre))

    # Deduplicate by title, keeping the highest match_score version
    seen: set[str] = set()
    unique = []
    for book in sorted(all_results, key=lambda b: b.get("match_score", 0), reverse=True):
        if book["title"] not in seen:
            seen.add(book["title"])
            unique.append(book)

    return unique[:10]


@app.get(
    "/recommendations/authors",
    response_model=List[BookResponse],
    tags=["Recommendations"],
    summary="Recommend by favourite author",
    description="Returns up to 10 books by the user's highest-rated author (requires >= 4 stars). Returns an empty list if there is not enough data.",
)
async def get_author_recommendations(uid: str = Depends(get_current_uid)):
    library_docs = [doc async for doc in async_db.collection("users").document(uid).collection("library").stream()]

    author_scores: dict[str, int] = {}
    for doc in library_docs:
        book = doc.to_dict()
        author = book.get("author", "").lower().strip()
        rating = book.get("rating", 0)
        if author and rating > 0:
            author_scores[author] = max(author_scores.get(author, 0), rating)

    if not author_scores:
        return []

    top_author = max(author_scores, key=lambda a: author_scores[a])
    if author_scores[top_author] < 4:
        return []

    user_genre_vector = build_user_genre_vector(library_docs)
    excluded = get_read_titles(library_docs)
    client: httpx.AsyncClient = app.state.http_client

    return await _author_recommendations(client, user_genre_vector, excluded, top_author)


@app.get(
    "/recommendations/similar/{book_id}",
    response_model=List[BookResponse],
    tags=["Recommendations"],
    summary="Find similar books",
    description="Returns up to 5 books similar to a specific book in the user's library.",
)
async def get_similar_books(book_id: str, uid: str = Depends(get_current_uid)):
    require_non_empty_id(book_id, "Book ID")
    doc = await _library_doc_async(uid, book_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Book not found in library.")

    target = doc.to_dict()
    genres = target.get("genres", [])
    if not genres:
        return []

    library_docs = [doc async for doc in async_db.collection("users").document(uid).collection("library").stream()]
    excluded = get_read_titles(library_docs) | {target.get("title", "")}
    user_genre_vector = build_user_genre_vector(library_docs) or DEFAULT_GENRE_VECTOR
    client: httpx.AsyncClient = app.state.http_client

    return await _genre_recommendations(client, user_genre_vector, excluded, genres[0], limit=5)


@app.get(
    "/recommendations/genre/{genre}",
    response_model=List[BookResponse],
    tags=["Recommendations"],
    summary="Recommend by specific genre",
)
async def get_specific_genre_recommendations(genre: str, uid: str = Depends(get_current_uid)):
    require_non_empty_id(genre, "Genre")
    library_docs = [doc async for doc in async_db.collection("users").document(uid).collection("library").stream()]
    user_genre_vector = build_user_genre_vector(library_docs) or DEFAULT_GENRE_VECTOR
    excluded = get_read_titles(library_docs)
    client: httpx.AsyncClient = app.state.http_client
    return await _genre_recommendations(client, user_genre_vector, excluded, genre.lower().strip())


@app.get(
    "/recommendations/author/{author}",
    response_model=List[BookResponse],
    tags=["Recommendations"],
    summary="Recommend by specific author",
)
async def get_specific_author_recommendations(author: str, uid: str = Depends(get_current_uid)):
    require_non_empty_id(author, "Author")
    library_docs = [doc async for doc in async_db.collection("users").document(uid).collection("library").stream()]
    user_genre_vector = build_user_genre_vector(library_docs) or DEFAULT_GENRE_VECTOR
    excluded = get_read_titles(library_docs)
    client: httpx.AsyncClient = app.state.http_client
    return await _author_recommendations(client, user_genre_vector, excluded, author.lower().strip())
