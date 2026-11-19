# Data Engineering Assignment

A small data pipeline that collects **7,000+ English Wikipedia articles about health and diseases**, stores them in **MongoDB**, and profiles their text.

```
Wikipedia API ──collect.py──► data/articles.csv ──load.py──► MongoDB ──profile.ipynb──► word stats & charts
```

## Project structure

| File | What it does |
|---|---|
| `collect.py` | Collects articles from the Wikipedia API and saves them to `data/articles.csv` |
| `wikipedia_client.py` | `WikipediaClient`: all HTTP details (retries, rate limiting, `continue` tokens) |
| `load.py` | Loads `data/articles.csv` into MongoDB |
| `db_context.py` | `DbContext`: owns the MongoDB connection (settings come from `.env`) |
| `article_repository.py` | `ArticleRepository`: **the only way** the code reads or writes articles in MongoDB |
| `profile.ipynb` | Runs the whole pipeline and the profiling steps 4a–4e (words, stopwords, charts, spelling) |
| `profile_checks.py` | Automatic checks for the profiling exercises (contains the answers) |
| `docker-compose.yml` | Runs MongoDB 8.0 in Docker, with a volume so data is kept |
| `Makefile` | Shortcuts for common commands (run `make` to list them) |
| `.env.example` | Template for your `.env` settings file |

## Requirements

- **Python 3.10+**
- **Docker Desktop** (for MongoDB)
- **make** (already installed on macOS and Linux)

## Setup (once)

1. **Create your settings file** and fill in your email:
   ```bash
   cp .env.example .env
   ```
   | Setting | Meaning |
   |---|---|
   | `MONGO_URI` | MongoDB address. The default matches `docker-compose.yml` |
   | `MONGO_DB` | Database name, any name you like |
   | `CONTACT_EMAIL` | **Required.** Wikipedia asks API users to include contact info in their requests |

   `.env` is in `.gitignore`, so your email is never committed.

2. **Create the Python environment and install the packages:**
   ```bash
   make install
   ```
   This creates the `data-engineering/` virtual environment (a private folder of packages for this project) and installs everything from `requirements.txt`.

3. **Start MongoDB:**
   ```bash
   docker compose up -d
   ```

## Run the pipeline

### Option A: in the notebook (recommended)

1. Open `profile.ipynb` in VS Code.
2. Click **Select Kernel** → **Python Environments** → `data-engineering`.
3. Run the cells from top to bottom:
   - **Step 1** collects the articles (`collect.main()`).
   - **Step 2** loads them into MongoDB (`load.main()`).
   - **Step 3** runs the profiling steps 4a–4e and shows the charts.

### Option B: from the terminal

```bash
make run FILE=collect.py   # Wikipedia → data/articles.csv
make run FILE=load.py      # data/articles.csv → MongoDB
```
Then open `profile.ipynb` for the profiling (Step 3).

### What each step does

- **Collect** (`collect.py`). Takes a few minutes the first time.
  1. Walks the categories *Diseases and disorders*, *Infectious diseases*, *Medical conditions* and *Symptoms and signs*, up to 3 levels deep, to find about 8,500 articles.
  2. Downloads each article's intro summary, 20 articles per request.
  3. Removes short summaries (under 30 words), "List of…" pages and disambiguation pages, then writes `data/articles.csv`.
  - **Safe to stop and re-run:** every downloaded batch is saved to `data/raw/articles.jsonl` right away, and articles already there are skipped.
- **Load** (`load.py`). Saves every row to the `articles` collection in MongoDB.
  - Articles are matched by `page_id`, so re-running updates them instead of creating duplicates.
  - A unique index on `page_id` also blocks duplicates at the database level.
- **Profile** (`profile.ipynb`, Step 3). Splits the summaries into words, then reports the most frequent words, stopwords (NLTK's English list) and spelling issues (pyspellchecker), with a word cloud and a bar chart.

## Working with the project

### Common commands

| Command | What it does |
|---|---|
| `make` | List all commands |
| `make install` | Install everything in `requirements.txt` |
| `make add PKG=name` | Install a package **and** save it to `requirements.txt` |
| `make remove PKG=name` | Uninstall a package and update `requirements.txt` |
| `make run FILE=x.py` | Run a Python file with the project's environment |
| `make shell` | Open a terminal with the environment active (`exit` to leave) |
| `make lint` / `make format` | Check / auto-format the code with ruff |
| `make clean` | Delete Python cache files |
| `make reset` | Delete and rebuild the environment from `requirements.txt` |

You don't need to activate the environment for `make` commands. To activate it in your own terminal: `source data-engineering/bin/activate`.

### Rules for the code

- **Database access goes through `ArticleRepository`.** Create one `DbContext` and pass it to the repository:
  ```python
  from db_context import DbContext
  from article_repository import ArticleRepository

  with DbContext() as context:
      repo = ArticleRepository(context)
      print(repo.count())
  ```
- **Wikipedia access goes through `WikipediaClient`.** It sends one request at a time, waits between requests, and retries on errors, as Wikipedia's API rules ask.
- **Add packages with `make add`**, not plain `pip install`, so `requirements.txt` stays up to date.

### Notebook tips

- The first cell turns on **autoreload**, so edits to `.py` files are picked up without restarting the kernel.
- **Restart the kernel** after you:
  - rename a file;
  - change a class's constructor (`__init__`);
  - edit `.env`;
  - upgrade an already-imported package.
- If a `.py` file or the notebook was changed outside VS Code, run **File: Revert File** to reload it from disk *before* saving.

## MongoDB data: is it kept?

**Yes.** `docker-compose.yml` stores MongoDB's files in a Docker **volume** named `mongo_data`. A volume is storage that lives outside the container, so the data survives when the container stops or is deleted.

| Command | Data kept? |
|---|---|
| `docker compose restart` / `stop` + `start` | ✅ Kept |
| Restarting Docker Desktop or your computer | ✅ Kept. The container also restarts by itself (`restart: unless-stopped`) |
| `docker compose down` (deletes the container) | ✅ Kept. `docker compose up -d` brings it back with the same data |
| `docker compose down -v` | ❌ **Deleted.** The `-v` flag also deletes the volume |
| `docker volume rm data-engineering-assignment_mongo_data` | ❌ **Deleted** |

If the data is lost, run `load.py` again (Step 2) to reload it from `data/articles.csv`.

## Data files

`data/` is in `.gitignore`, so the data isn't in the repository. Running `collect.py` recreates it:

| File | Contents |
|---|---|
| `data/raw/articles.jsonl` | Every downloaded article, one JSON object per line (the progress file used to resume) |
| `data/articles.csv` | The cleaned dataset loaded into MongoDB |

**Columns:**
- `page_id`, `title`, `url`, `summary`
- `source_category`, `category_depth`
- `word_count`, `char_count`, `page_length_bytes`
- `last_edited`, `scraped_at`

## Troubleshooting

| Problem | Fix |
|---|---|
| `CONTACT_EMAIL is not set` | Add `CONTACT_EMAIL=you@example.com` to `.env` |
| `ServerSelectionTimeoutError` when connecting to MongoDB | Docker isn't running, or MongoDB isn't started: `docker compose up -d` |
| `data-engineering` is missing from the kernel list | Run `make reset`, then **Developer: Reload Window** in VS Code |
| `ModuleNotFoundError` in the notebook | The wrong kernel is selected. Pick `data-engineering` |
| The notebook runs old code after editing a `.py` file | Restart the kernel and run the first (autoreload) cell |
| `0 articles in MongoDB` | Step 2 (`load.main()`) hasn't been run against this database yet |
