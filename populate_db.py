import os
from datetime import datetime, timezone
from google.cloud import firestore

# 1. Connect to the database
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-keys.json"
db = firestore.Client()

# 2. Dataset using strictly top-level Google Books API (BISAC) categories
dummy_data = [
    # --- LORENZO'S LIBRARY ("Computers" and "Science") ---
    {"user": "lorenzo_test", "id": "b_hawk", "title": "A Brief History of Time", "author": "Stephen Hawking", "genres": ["Science"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_sagan", "title": "Cosmos", "author": "Carl Sagan", "genres": ["Science"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_prag", "title": "The Pragmatic Programmer", "author": "Andrew Hunt", "genres": ["Computers"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_clean", "title": "Clean Code", "author": "Robert C. Martin", "genres": ["Computers"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_ai", "title": "Artificial Intelligence", "author": "Stuart Russell", "genres": ["Computers"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_gene", "title": "The Selfish Gene", "author": "Richard Dawkins", "genres": ["Science"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_codecomp", "title": "Code Complete", "author": "Steve McConnell", "genres": ["Computers"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_algo", "title": "Introduction to Algorithms", "author": "Thomas H. Cormen", "genres": ["Computers"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_astro", "title": "Astrophysics for People in a Hurry", "author": "Neil deGrasse Tyson", "genres": ["Science"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_hack", "title": "Hackers", "author": "Steven Levy", "genres": ["Computers"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_sicp", "title": "Structure and Interpretation of Computer Programs", "author": "Harold Abelson", "genres": ["Computers"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_eleg", "title": "The Elegant Universe", "author": "Brian Greene", "genres": ["Science"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_design", "title": "Design Patterns", "author": "Erich Gamma", "genres": ["Computers"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_myth", "title": "The Mythical Man-Month", "author": "Frederick P. Brooks Jr.", "genres": ["Computers"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_brief", "title": "Brief Answers to the Big Questions", "author": "Stephen Hawking", "genres": ["Science"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_feynman", "title": "The Feynman Lectures on Physics", "author": "Richard P. Feynman", "genres": ["Science"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_six", "title": "Six Easy Pieces", "author": "Richard P. Feynman", "genres": ["Science"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_codelang", "title": "Code: The Hidden Language of Computer Hardware", "author": "Charles Petzold", "genres": ["Computers"], "rating": 5},
    {"user": "lorenzo_test", "id": "b_silent", "title": "Silent Spring", "author": "Rachel Carson", "genres": ["Science"], "rating": 4},
    {"user": "lorenzo_test", "id": "b_network", "title": "Computer Networking", "author": "James F. Kurose", "genres": ["Computers"], "rating": 4},

    # --- PIETRO'S LIBRARY ("True Crime", "Psychology", "Philosophy") ---
    {"user": "pietro_test", "id": "b_cold", "title": "In Cold Blood", "author": "Truman Capote", "genres": ["True Crime"], "rating": 5},
    {"user": "pietro_test", "id": "b_dark", "title": "I'll Be Gone in the Dark", "author": "Michelle McNamara", "genres": ["True Crime"], "rating": 4},
    {"user": "pietro_test", "id": "b_med", "title": "Meditations", "author": "Marcus Aurelius", "genres": ["Philosophy"], "rating": 5},
    {"user": "pietro_test", "id": "b_nietz", "title": "Beyond Good and Evil", "author": "Friedrich Nietzsche", "genres": ["Philosophy"], "rating": 4},
    {"user": "pietro_test", "id": "b_kahn", "title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "genres": ["Psychology"], "rating": 5},
    {"user": "pietro_test", "id": "b_frankl", "title": "Man's Search for Meaning", "author": "Viktor E. Frankl", "genres": ["Psychology"], "rating": 5},
    {"user": "pietro_test", "id": "b_mind", "title": "Mindhunter", "author": "John E. Douglas", "genres": ["True Crime"], "rating": 4},
    {"user": "pietro_test", "id": "b_helt", "title": "Helter Skelter", "author": "Vincent Bugliosi", "genres": ["True Crime"], "rating": 5},
    {"user": "pietro_test", "id": "b_plato", "title": "The Republic", "author": "Plato", "genres": ["Philosophy"], "rating": 3},
    {"user": "pietro_test", "id": "b_sun", "title": "The Art of War", "author": "Sun Tzu", "genres": ["Philosophy"], "rating": 4},
    {"user": "pietro_test", "id": "b_cial", "title": "Influence", "author": "Robert B. Cialdini", "genres": ["Psychology"], "rating": 4},
    {"user": "pietro_test", "id": "b_zod", "title": "Zodiac", "author": "Robert Graysmith", "genres": ["True Crime"], "rating": 4},
    {"user": "pietro_test", "id": "b_kant", "title": "Critique of Pure Reason", "author": "Immanuel Kant", "genres": ["Philosophy"], "rating": 3},
    {"user": "pietro_test", "id": "b_psy", "title": "The Psychopath Test", "author": "Jon Ronson", "genres": ["Psychology"], "rating": 4},
    {"user": "pietro_test", "id": "b_rule", "title": "The Stranger Beside Me", "author": "Ann Rule", "genres": ["True Crime"], "rating": 5},
    {"user": "pietro_test", "id": "b_quiet", "title": "Quiet", "author": "Susan Cain", "genres": ["Psychology"], "rating": 5},
    {"user": "pietro_test", "id": "b_blink", "title": "Blink", "author": "Malcolm Gladwell", "genres": ["Psychology"], "rating": 4},
    {"user": "pietro_test", "id": "b_zara", "title": "Thus Spoke Zarathustra", "author": "Friedrich Nietzsche", "genres": ["Philosophy"], "rating": 4},
    {"user": "pietro_test", "id": "b_columbine", "title": "Columbine", "author": "Dave Cullen", "genres": ["True Crime"], "rating": 5},
    {"user": "pietro_test", "id": "b_flow", "title": "Flow", "author": "Mihaly Csikszentmihalyi", "genres": ["Psychology"], "rating": 4},

    # --- CELIA'S LIBRARY ("Fiction", "Cooking", "Art") ---
    {"user": "celia_test", "id": "b_pride", "title": "Pride and Prejudice", "author": "Jane Austen", "genres": ["Fiction"], "rating": 5},
    {"user": "celia_test", "id": "b_lotr", "title": "The Lord of the Rings", "author": "J.R.R. Tolkien", "genres": ["Fiction"], "rating": 5},
    {"user": "celia_test", "id": "b_julia", "title": "Mastering the Art of French Cooking", "author": "Julia Child", "genres": ["Cooking"], "rating": 5},
    {"user": "celia_test", "id": "b_salt", "title": "Salt, Fat, Acid, Heat", "author": "Samin Nosrat", "genres": ["Cooking"], "rating": 5},
    {"user": "celia_test", "id": "b_art", "title": "The Story of Art", "author": "E.H. Gombrich", "genres": ["Art"], "rating": 4},
    {"user": "celia_test", "id": "b_ways", "title": "Ways of Seeing", "author": "John Berger", "genres": ["Art"], "rating": 4},
    {"user": "celia_test", "id": "b_out", "title": "Outlander", "author": "Diana Gabaldon", "genres": ["Fiction"], "rating": 5},
    {"user": "celia_test", "id": "b_name", "title": "The Name of the Wind", "author": "Patrick Rothfuss", "genres": ["Fiction"], "rating": 5},
    {"user": "celia_test", "id": "b_got", "title": "A Game of Thrones", "author": "George R.R. Martin", "genres": ["Fiction"], "rating": 4},
    {"user": "celia_test", "id": "b_joy", "title": "The Joy of Cooking", "author": "Irma S. Rombauer", "genres": ["Cooking"], "rating": 4},
    {"user": "celia_test", "id": "b_lab", "title": "The Food Lab", "author": "J. Kenji López-Alt", "genres": ["Cooking"], "rating": 5},
    {"user": "celia_test", "id": "b_steal", "title": "Steal Like an Artist", "author": "Austin Kleon", "genres": ["Art"], "rating": 4},
    {"user": "celia_test", "id": "b_emma", "title": "Emma", "author": "Jane Austen", "genres": ["Fiction"], "rating": 4},
    {"user": "celia_test", "id": "b_hp", "title": "Harry Potter and the Sorcerer's Stone", "author": "J.K. Rowling", "genres": ["Fiction"], "rating": 5},
    {"user": "celia_test", "id": "b_plenty", "title": "Plenty", "author": "Yotam Ottolenghi", "genres": ["Cooking"], "rating": 5},
    {"user": "celia_test", "id": "b_color", "title": "Interaction of Color", "author": "Josef Albers", "genres": ["Art"], "rating": 3},
    {"user": "celia_test", "id": "b_me", "title": "Me Before You", "author": "Jojo Moyes", "genres": ["Fiction"], "rating": 4},
    {"user": "celia_test", "id": "b_mist", "title": "Mistborn", "author": "Brandon Sanderson", "genres": ["Fiction"], "rating": 5},
    {"user": "celia_test", "id": "b_ital", "title": "Essentials of Classic Italian Cooking", "author": "Marcella Hazan", "genres": ["Cooking"], "rating": 5},
    {"user": "celia_test", "id": "b_notebook", "title": "The Notebook", "author": "Nicholas Sparks", "genres": ["Fiction"], "rating": 4},
]

print(f"Starting database population with {len(dummy_data)} books...")

for count, data in enumerate(dummy_data, 1):
    doc_ref = db.collection("users").document(data["user"]).collection("library").document(data["id"])

    doc_ref.set({
        "title": data["title"],
        "author": data["author"],
        "genres": data["genres"],
        "rating": data["rating"],
        "status": "read",
        "added_at": datetime.now(timezone.utc)
    })
    print(f"[{count}/60] Added '{data['title']}' to {data['user']}'s library")

print("Database successfully populated! You are ready to test.")