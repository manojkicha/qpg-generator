import jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

# Retrieve the secret key from settings (which loads from environment variables)
SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"

# This creates the "Authorize" button in Swagger UI
security = HTTPBearer()

async def validate_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    FastAPI dependency to validate JWT token.
    This will automatically appear in Swagger docs as a security requirement.
    """
    token = credentials.credentials
    try:
        # Decrypt/Verify the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Token: Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Token"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Token: {str(e)}"
        )
