# BuscadorDGI

## 🗄️ Database Configuration

### Local Development
Uses SQLite automatically (`data/app.sqlite3`). No configuration needed.

### Production (Streamlit Cloud)
Uses PostgreSQL (Neon) for persistent storage.

**Setup**:
1. Create a free Neon project at https://neon.tech
2. Copy the connection string
3. In Streamlit Cloud → Settings → Secrets, add:
   ```toml
   [database]
   url = "postgresql://user:password@host/database?sslmode=require"
   ```
4. Deploy the app

**Migrate existing data**:
```bash
# Run locally (with Streamlit secrets configured)
python scripts/migrate_to_neon.py
```

---

## Testing

**Test locally** (should use SQLite):
```bash
streamlit run app.py
```

**Test with PostgreSQL locally** (optional):
Create `.streamlit/secrets.toml`:
```toml
[database]
url = "postgresql://..."
```

Then run the app - it will use PostgreSQL instead of SQLite.

---

## Implementation Notes

- Auto-detects environment: checks for `st.secrets["database"]["url"]`
- Backward compatible: existing local dev workflows unchanged
- All SQL queries work on both SQLite and PostgreSQL
- Placeholder syntax (`?` vs `%s`) handled automatically
- Foreign key constraints preserved
- Indexes created for performance