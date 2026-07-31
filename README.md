# Readar API

Backend API built with **FastAPI** for the **Readar** Android application. The service handles book searches via the Google Books API, personal library storage on **Google Cloud Firestore**, user authentication via **Firebase Admin**, and a personalized recommendation system based on quantitative genre preference scoring.

---

## Key Features

* **Book Search & Catalog:**
* Asynchronous integration with the Google Books API, featuring automatic retry logic with exponential backoff.
* Two-tier in-memory caching system (`TTLCache`) to optimize response times and reduce external network calls (12-hour TTL for search results, 10-minute TTL for trending books).
* Calculation of trending books over the last 30 days by aggregating data across all user libraries in Firestore.


* **Personal Library Management:**
* Full CRUD operations (Create, Read, Update, Delete) for books saved by the user.
* Reading status tracking (`reading`, `read`) and numerical ratings from 1 to 5 stars.


* **Recommendation System:**
* Personalized book suggestions generated from user ratings across individual literary genres and authors.
* Quantitative similarity scoring between the user's taste profile and catalog items.


* **Security & Authentication:**
* Firebase Authentication JWT token verification on all protected endpoints using `HTTPBearer`.



---

## Architecture & Tech Stack

| Component | Technology | Usage in Project |
| --- | --- | --- |
| **Web Framework** | FastAPI (Python 3.10+) | Asynchronous HTTP request handling and validation with Pydantic v2. |
| **Database** | Google Cloud Firestore | Storage for user profiles and libraries using both sync and async clients. |
| **Authentication** | Firebase Admin SDK | JWT token validation and secure user identification (`uid`). |
| **HTTP Client** | `httpx.AsyncClient` | Non-blocking HTTP requests to the Google Books API with timeouts and retry backoff. |
| **Caching** | `cachetools.TTLCache` | Time-to-live memory caching with LRU eviction to control resource usage. |

---

## Recommendation Algorithm

The system assigns a compatibility score (`match_score`) to each analyzed book by combining two metrics: **genre similarity (80%)** and **book popularity (20%)**.

1. **User Preference Vector:** The system aggregates genres from positively rated books in the user's library, assigning each genre a weighted frequency based on the star rating.
2. **Cosine Similarity:** To compare the user profile ($A$) against a candidate book's genre vector ($B$), cosine similarity is calculated:

$$\text{similarity}(A, B) = \frac{\sum_{i=1}^{n} A_i B_i}{\sqrt{\sum_{i=1}^{n} A_i^2} \sqrt{\sum_{i=1}^{n} B_i^2}}$$


3. **Final Score:** Popularity is normalized against the Google Books review count (capped at 10,000 reviews):

$$\text{Score} = \left( \text{similarity} \times 0.8 + \min\left(\frac{\text{ratings}}{10000}, 1.0\right) \times 0.2 \right) \times 100$$



---

## Prerequisites & Setup

### 1. System Requirements

* Python **3.10** or higher.
* A Google Cloud / Firebase project with **Firestore** and **Firebase Authentication** enabled.
* A valid API key for the **Google Books API**.

### 2. Environment Variables & Credentials

Set the required environment variables before starting the server:

```bash
# Google Books API Key
export GOOGLE_BOOKS_API_KEY="your_google_books_api_key"

# Path to your Firebase/GCP service account credentials JSON file
export GOOGLE_APPLICATION_CREDENTIALS="google-keys.json"

```

> **Note:** If `google-keys.json` is placed directly in the project root directory, the application loads it automatically.

### 3. Dependency Installation

Create a virtual environment and install the required packages:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install fastapi uvicorn httpx cachetools google-cloud-firestore firebase-admin pydantic

```

### 4. Running the Server

Start the development server with live reload enabled:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

```

The API will be available at `http://localhost:8000`. Interactive OpenAPI documentation (Swagger UI) is accessible at `http://localhost:8000/docs`.

---

## API Endpoints Overview

### Public & Search

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/` | Service health check. |
| `GET` | `/search/{query}` | Search books in the Google Books catalog (max 30 results). |
| `GET` | `/trending` | Returns the 10 most-added books across all users in the last 30 days. |
| `GET` | `/books/{book_id}` | Retrieve details for a single book by its Google Books ID. |

### User Profile (Requires Bearer JWT Authentication)

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/profile` | Create or update a user profile in Firestore. |
| `GET` | `/profile` | Retrieve profile data for the authenticated user. |
| `PATCH` | `/profile` | Update specific profile fields (name, email, profile image). |

### Personal Library (Requires Bearer JWT Authentication)

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/library/add` | Add a new book to the user's library. |
| `GET` | `/library` | Return the full list of books in the user's library. |
| `GET` | `/library/latest` | Return the most recently added book in chronological order. |
| `GET` | `/library/{book_id}` | Return data for a specific book stored in the library. |
| `PUT` | `/library/{book_id}/rate` | Assign a numerical rating from 1 to 5 stars. |
| `PATCH` | `/library/{book_id}/status` | Update reading status (`reading` or `read`). |
| `DELETE` | `/library/{book_id}` | Remove a book from the user's library. |

### Recommendations (Requires Bearer JWT Authentication)

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/recommendations/genres` | Return books based on the user's top 2 genres. |
| `GET` | `/recommendations/authors` | Return books by the user's highest-rated author ($\ge 4$ stars). |
| `GET` | `/recommendations/similar/{book_id}` | Return books with genres similar to a specific volume in the library. |
| `GET` | `/recommendations/genre/{genre}` | Recommendations filtered by a specific genre, ranked by affinity score. |
| `GET` | `/recommendations/author/{author}` | Recommendations filtered by a specific author, ranked by affinity score. |
