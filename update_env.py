content = """# Application
DEBUG=True
SECRET_KEY=C1FypP1e5c4uajYmTKCyBsa8EqeN4EVgddk6uw09EaDk7qBjU4rrwROFils-5xj5
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:8000"]

# Google Gemini API
GOOGLE_API_KEY=AIzaSyBL9YTbE0SllCIRI3DE25YWIY9CqxNeI9g

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/app.db

# File Search
FS_MAIN_STORE_NAME=main-store
FS_RUBRIC_STORE_NAME=rubric-store

# File Upload
MAX_UPLOAD_SIZE=52428800
UPLOAD_DIR=./data/uploads

# Models
GEMINI_QNA_MODEL=gemini-2.5-flash
GEMINI_EVAL_MODEL=gemini-2.5-pro

# Google Cloud Configuration
GOOGLE_APPLICATION_CREDENTIALS=./credentials/google-cloud-key.json
GOOGLE_PROJECT_ID=your-google-project-id

# Vector DB Paths (Criteria vs User separation)
CRITERIA_VECTOR_DB_PATH=./data/vector_db/criteria/
USER_VECTOR_DB_PATH=./data/vector_db/user/

# Criteria Upload
CRITERIA_UPLOAD_DIR=./data/uploads/criteria/
"""

with open(".env", "w") as f:
    f.write(content)
print("Updated .env to gemini-2.5-flash")
