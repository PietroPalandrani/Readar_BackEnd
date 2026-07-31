# Readar

A RESTful API service built with FastAPI, Google Cloud Firestore, and the Google Books API. Readar allows users to search for books, maintain a personal reading library, rate books, track reading statuses, and receive personalized recommendations calculated using vector similarity.

---

## Features

* **Book Search & Catalog:** Query the Google Books API for book details, authors, genres, and thumbnails.
* **Library Management:** Users can add books to their personal Firestore library, track reading progress (`to_read`, `reading`, `read`), assign star ratings (1–5), and delete books.
* **Vector-Based Recommendations:** Employs cosine similarity between user genre rating profiles and book genre vectors to generate tailored recommendations by genre, author, or similar titles.
* **Community Trending:** Uses Firestore Collection Group queries to identify the most frequently added books across all user libraries over the last 30 days.
* **User Profiles:** Create and update user profile data (name, email, profile image).

---

## Tech Stack

* **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
* **Database:** Google Cloud Firestore (NoSQL)
* **External API:** Google Books API
* **Data Validation:** Pydantic
* **HTTP Client:** Requests

---

## Prerequisites

1. **Python 3.10+**
2. **Google Cloud Project:** With the Firestore API enabled.
3. **Google Books API Key:** Generated from the Google Cloud Console.
4. **Service Account Key:** A JSON credentials file (`google-keys.json`) with Firestore read/write permissions.

---

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/yourusername/readar-backend.git](https://github.com/yourusername/readar-backend.git)
   cd readar-backend
