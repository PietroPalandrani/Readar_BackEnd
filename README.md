# Readar API

Backend API sviluppato con **FastAPI** per l'applicazione Android **Readar**. Il servizio gestisce la ricerca dei libri tramite Google Books API, la memorizzazione delle librerie personali degli utenti su **Google Cloud Firestore**, l'autenticazione tramite **Firebase Admin** e un sistema di raccomandazione personalizzato basato sul calcolo numerico delle preferenze di genere.

---

## Funzionalità Principali

* **Ricerca e Catalogo Libri:**
* Integrazione asincrona con l'API di Google Books con gestione automatica dei retry (exponential backoff).
* Sistema di caching in memoria (`TTLCache`) a due livelli per ottimizzare le risposte e ridurre le chiamate di rete esterne (TTL di 12 ore per le ricerche, 10 minuti per i libri in tendenza).
* Calcolo dei libri in tendenza negli ultimi 30 giorni aggregando i dati di tutte le librerie utente su Firestore.


* **Gestione Libreria Personale:**
* Operazioni complete di inserimento, lettura, aggiornamento ed eliminazione (CRUD) per i libri salvati dall'utente.
* Tracciamento dello stato di lettura (`reading`, `read`) e valutazione numerica da 1 a 5 stelle.


* **Sistema di Raccomandazione:**
* Generazione di suggerimenti personalizzati basati sulle valutazioni assegnate dall'utente ai singoli generi letterari e agli autori.
* Calcolo di similarità quantitativa tra il profilo utente e i libri del catalogo.


* **Sicurezza e Autenticazione:**
* Verifica dei token JWT di Firebase Authentication su ogni endpoint protetto tramite `HTTPBearer`.



---

## Architettura e Tecnologie

| Componente | Tecnologia | Utilizzo nel Progetto |
| --- | --- | --- |
| **Framework Web** | FastAPI (Python 3.10+) | Gestione asincrona delle richieste HTTP e validazione con Pydantic v2. |
| **Database** | Google Cloud Firestore | Archiviazione dei profili utente e delle librerie tramite client sincrono e asincrono. |
| **Autenticazione** | Firebase Admin SDK | Validazione dei token JWT e identificazione sicura degli utenti (`uid`). |
| **Client HTTP** | `httpx.AsyncClient` | Chiamate HTTP non bloccanti verso Google Books API con timeout e backoff. |
| **Caching** | `cachetools.TTLCache` | Cache in memoria con scadenza temporale e rimozione LRU per limitare l'uso di risorse. |

---

## Algoritmo di Raccomandazione

Il sistema assegna un punteggio di compatibilità (`match_score`) a ciascun libro analizzato combinando due indici: **similarità di genere (80%)** e **popolarità del libro (20%)**.

1. **Vettore delle Preferenze Utente:** Il sistema aggrega i generi dei libri valutati positivamente nella libreria dell'utente, associando a ciascun genere una frequenza pesata in base al punteggio in stelle assegnato.
2. **Similarità del Coseno:** Per confrontare il profilo utente ($A$) con il vettore dei generi di un libro candidato ($B$), si calcola la similarità del coseno:

$$\text{similarity}(A, B) = \frac{\sum_{i=1}^{n} A_i B_i}{\sqrt{\sum_{i=1}^{n} A_i^2} \sqrt{\sum_{i=1}^{n} B_i^2}}$$


3. **Punteggio Finale:** La popolarità viene normalizzata sul numero di recensioni di Google Books (con tetto massimo a 10.000 recensioni):

$$\text{match\_score} = \left( \text{similarity} \times 0.8 + \min\left(\frac{\text{ratings\_count}}{10000}, 1.0\right) \times 0.2 \right) \times 100$$



---

## Prerequisiti e Configurazione

### 1. Requisiti di Sistema

* Python **3.10** o superiore.
* Un progetto Google Cloud / Firebase con **Firestore** e **Firebase Authentication** abilitati.
* Una chiave API valida per **Google Books API**.

### 2. Variabili d'Ambiente e Credenziali

Crea le variabili d'ambiente necessarie prima di avviare il server:

```bash
# Chiave API per Google Books
export GOOGLE_BOOKS_API_KEY="la_tua_api_key_google_books"

# Percorso verso il file di credenziali dell'account di servizio Firebase/GCP
export GOOGLE_APPLICATION_CREDENTIALS="google-keys.json"

```

> **Nota:** Se il file `google-keys.json` è presente direttamente nella directory radice del progetto, l'applicazione lo caricherà automaticamente.

### 3. Installazione delle Dipendenze

Crea un ambiente virtuale e installa i pacchetti richiesti:

```bash
python -m venv venv
source venv/bin/activate  # Su Windows: venv\Scripts\activate
pip install fastapi uvicorn httpx cachetools google-cloud-firestore firebase-admin pydantic

```

### 4. Avvio del Server

Per avviare il server in ambiente di sviluppo con autoricarica:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

```

L'API sarà disponibile all'indirizzo `http://localhost:8000`. La documentazione interattiva OpenAPI (Swagger) è accessibile su `http://localhost:8000/docs`.

---

## Riepilogo degli Endpoint API

### Pubblici & Ricerca

| Metodo | Endpoint | Descrizione |
| --- | --- | --- |
| `GET` | `/` | Controllo di stato del servizio (Health check). |
| `GET` | `/search/{query}` | Cerca libri nel catalogo di Google Books (max 30 risultati). |
| `GET` | `/trending` | Restituisce i 10 libri più aggiunti dagli utenti negli ultimi 30 giorni. |
| `GET` | `/books/{book_id}` | Recupera i dettagli di un singolo libro tramite ID Google Books. |

### Profilo Utente (Richiede Autenticazione Bearer JWT)

| Metodo | Endpoint | Descrizione |
| --- | --- | --- |
| `POST` | `/profile` | Crea o aggiorna un profilo utente nel database Firestore. |
| `GET` | `/profile` | Restituisce i dati del profilo dell'utente autenticato. |
| `PATCH` | `/profile` | Aggiorna campi specifici del profilo (nome, email, immagine). |

### Libreria Personale (Richiede Autenticazione Bearer JWT)

| Metodo | Endpoint | Descrizione |
| --- | --- | --- |
| `POST` | `/library/add` | Aggiunge un nuovo libro alla libreria dell'utente. |
| `GET` | `/library` | Restituisce l'elenco completo dei libri nella libreria dell'utente. |
| `GET` | `/library/latest` | Restituisce l'ultimo libro inserito in ordine cronologico. |
| `GET` | `/library/{book_id}` | Restituisce i dati di uno specifico libro presente in libreria. |
| `PUT` | `/library/{book_id}/rate` | Assegna una valutazione numerica da 1 a 5 stelle. |
| `PATCH` | `/library/{book_id}/status` | Aggiorna lo stato di lettura (`reading` o `read`). |
| `DELETE` | `/library/{book_id}` | Rimuove un libro dalla libreria utente. |

### Raccomandazioni (Richiede Autenticazione Bearer JWT)

| Metodo | Endpoint | Descrizione |
| --- | --- | --- |
| `GET` | `/recommendations/genres` | Restituisce libri basati sui 2 generi preferiti dell'utente. |
| `GET` | `/recommendations/authors` | Restituisce libri dell'autore con la valutazione più alta ($\ge 4$ stelle). |
| `GET` | `/recommendations/similar/{book_id}` | Restituisce libri con generi simili a un volume presente in libreria. |
| `GET` | `/recommendations/genre/{genre}` | Raccomandazioni filtrate per un genere specifico, ordinate per affinità. |
| `GET` | `/recommendations/author/{author}` | Raccomandazioni filtrate per un autore specifico, ordinate per affinità. |
