from supabase import create_client, Client
from config import settings

supabase: Client = create_client(settings.SUPABASE_PROJECT_URL, settings.SUPABASE_SECRET_KEY)
