import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import jwt

logger = logging.getLogger(__name__)

# Configuration - in production these should be in settings.py
SECRET_KEY = "super-secret-key-for-demo"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

router = APIRouter(prefix="/auth", tags=["auth"])

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None
    tenant_id: str | None = None

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Dependency to verify JWT and return user/tenant info."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        tenant_id: str = payload.get("tenant_id")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return {"username": username, "tenant_id": tenant_id}
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login", response_model=Token, summary="User login")
async def login(request: LoginRequest):
    """
    Authenticates user and returns a JWT token.
    For demo purposes: accepts admin/admin@123
    """
    # Demo credentials matching UI
    if request.username == "admin" and request.password == "admin@123":
        # We associate 'admin' with a default tenant_id for now
        token_data = {
            "sub": request.username,
            "tenant_id": "demo-tenant-123"
        }
        access_token = create_access_token(data=token_data)
        return Token(access_token=access_token, token_type="bearer")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )
