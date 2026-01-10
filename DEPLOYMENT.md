# Cloudflare + Railway Deployment Guide

## Architecture
- **Frontend**: Cloudflare Pages (static files)
- **Backend**: Railway (Flask API + SQLite)
- **Database**: SQLite on Railway server
- **Domain**: Cloudflare

---

## STEP 1: Prepare GitHub Repository

### 1.1 Create GitHub Repository
```bash
git init
git add .
git commit -m "Initial commit for deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/BotV2.git
git push -u origin main
```

### 1.2 Create `.gitignore`
```
__pycache__/
*.pyc
instance/
.env
.env.local
venv/
.DS_Store
```

---

## STEP 2: Update Flask App for Production

### 2.1 Create `railway.json`
This tells Railway how to run your app.

### 2.2 Create `requirements.txt` (root level)
Ensure all dependencies are listed:
- flask
- flask-cors
- python-dotenv
- requests
- sqlalchemy

### 2.3 Create `.env.example`
Shows what environment variables are needed (but don't commit actual secrets)

---

## STEP 3: Deploy Backend on Railway

### 3.1 Sign Up & Setup
1. Go to [railway.app](https://railway.app)
2. Click "Start New Project"
3. Select "Deploy from GitHub"
4. Authorize Railway with GitHub
5. Select your BotV2 repository

### 3.2 Configure Railway
1. Railway auto-detects Python
2. Click "Add Variables" and set:
   ```
   FLASK_ENV=production
   DATABASE_URL=sqlite:///instance/app.db
   TORN_API_KEY=YOUR_TORN_API_KEY
   SECRET_KEY=generate_random_string_here
   ```
3. Click "Deploy"

### 3.3 Get Railway Backend URL
After deployment, Railway gives you a URL like:
```
https://botv2-production-xxxx.railway.app
```
**Save this URL** - you'll need it for Cloudflare.

---

## STEP 4: Configure Frontend for Cloudflare Pages

### 4.1 Create `wrangler.toml` (in root)
```toml
name = "botv2-frontend"
type = "javascript"
```

### 4.2 Create `_headers` (in static folder)
Configures CORS to communicate with Railway:
```
/*
  Access-Control-Allow-Origin: https://botv2-production-xxxx.railway.app
  Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
  Access-Control-Allow-Headers: Content-Type, Authorization
```

### 4.3 Update JavaScript API Calls
In your frontend code, replace:
```javascript
// OLD:
fetch('/api/endpoint')

// NEW:
fetch('https://botv2-production-xxxx.railway.app/api/endpoint')
```

### 4.4 Configure Flask CORS (Backend)
Update `app.py` with:
```python
CORS(app, resources={
    r"/*": {
        "origins": ["https://yourdomain.com", "http://localhost:3000"],
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})
```

---

## STEP 5: Deploy Frontend on Cloudflare Pages

### 5.1 Sign Up for Cloudflare
1. Go to [cloudflare.com](https://cloudflare.com)
2. Sign up for free account
3. Add your domain (or use `pages.dev` subdomain)

### 5.2 Connect GitHub to Cloudflare Pages
1. Go to Cloudflare Dashboard → Pages
2. Click "Create a project" → "Connect to Git"
3. Authorize GitHub
4. Select your BotV2 repo
5. Configure build settings:
   - **Framework**: None (custom)
   - **Build command**: `echo "Static files only"`
   - **Build output directory**: `static`
   - **Root directory**: `/`

### 5.3 Set Build Environment Variables
In Cloudflare Pages project settings:
```
API_URL=https://botv2-production-xxxx.railway.app
```

### 5.4 Deploy
Click deploy - Cloudflare will serve your `static/` folder.

---

## STEP 6: Update Flask Configuration

### 6.1 Modify `app.py`
Add production configuration:

```python
import os

app.config['ENV'] = os.getenv('FLASK_ENV', 'production')
app.config['DEBUG'] = os.getenv('DEBUG', 'False') == 'True'

# CORS Configuration
CORS(app, resources={
    r"/api/*": {
        "origins": [
            os.getenv('FRONTEND_URL', 'http://localhost:3000'),
            'https://yourdomain.com'
        ],
        "supports_credentials": True
    }
})
```

### 6.2 Environment Variables Needed on Railway
```
FLASK_ENV=production
DEBUG=False
SECRET_KEY=your_secret_key_here
TORN_API_KEY=your_torn_api_key
DATABASE_URL=sqlite:///instance/app.db
FRONTEND_URL=https://yourdomain.com
```

---

## STEP 7: Connect Domain (Optional)

### 7.1 Point Domain to Cloudflare
1. In Cloudflare Dashboard → DNS
2. Update nameservers to Cloudflare's
3. Or add CNAME: `yourdomain.com` → `pages.dev`

### 7.2 Enable HTTPS
Cloudflare automatically provides SSL certificate.

---

## STEP 8: Test Deployment

### 8.1 Test API Calls
Open browser console and test:
```javascript
fetch('https://botv2-production-xxxx.railway.app/api/check-limits')
  .then(r => r.json())
  .then(console.log)
```

### 8.2 Test Frontend
Visit your Cloudflare Pages URL and verify:
- Static files load
- API calls work
- Dark mode works
- User history loads

### 8.3 Monitor Railway
In Railway Dashboard:
- Check deployment logs
- Monitor database
- View recent deployments

---

## STEP 9: Database Persistence

### 9.1 SQLite on Railway
Railway persists data in `/instance/app.db` automatically.

### 9.2 Backup Database
Download from Railway → Storage section (if needed).

---

## Troubleshooting

### CORS Errors
- Check `FRONTEND_URL` env var
- Verify `_headers` file in Cloudflare
- Check Flask CORS configuration

### API 404 Errors
- Verify Railway backend URL
- Check all endpoints in `routes/`
- Test with curl: `curl https://railway-url/api/endpoint`

### Database Connection
- Verify `DATABASE_URL` environment variable
- Check SQLite file exists on Railway
- Review Railway logs

### Static Files Not Loading
- Ensure files are in `static/` folder
- Check `build output directory` in Cloudflare
- Clear browser cache

---

## Quick Reference URLs

| Component | URL | Notes |
|-----------|-----|-------|
| Railway Backend | `https://botv2-production-xxxx.railway.app` | Your API server |
| Cloudflare Pages | `https://yourdomain.com` | Your frontend |
| Railway Dashboard | `https://railway.app/dashboard` | Monitor backend |
| Cloudflare Dashboard | `https://dash.cloudflare.com` | Manage frontend |

---

## Next Steps

1. Push code to GitHub
2. Deploy on Railway
3. Deploy on Cloudflare Pages
4. Connect domain
5. Test all features
6. Monitor logs
7. Setup automatic deployments (already enabled by default)

