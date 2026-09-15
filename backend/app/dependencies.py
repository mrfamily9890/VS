from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import get_db
from .config import get_settings
from .models import User
from .security import decode_access_token, decode_supabase_token, decode_token_version

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), database: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")
    try:
        settings = get_settings()
        if settings.auth_provider == "supabase":
            try:
                claims = decode_supabase_token(token)
                subject = str(claims["sub"])
                email = str(claims.get("email", "")).lower()
                user = database.scalar(select(User).where(User.supabase_user_id == subject))
                if user is None and email:
                    user = database.scalar(select(User).where(User.email == email))
                    if user is not None:
                        user.supabase_user_id = subject
                        database.commit()
            except Exception:
                if settings.environment.lower() != "development":
                    raise
                user_id = decode_access_token(token)
                token_version = decode_token_version(token)
                user = database.get(User, user_id)
                if user is None or user.token_version != token_version:
                    raise credentials_error
        else:
            user_id = decode_access_token(token)
            token_version = decode_token_version(token)
            user = database.get(User, user_id)
            if user is None or user.token_version != token_version:
                raise credentials_error
        if user is None:
            raise credentials_error
        if database.bind is not None and database.bind.dialect.name == "postgresql":
            database.execute(
                text("select set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(user.organization_id)},
            )
        return user
    except Exception as error:
        raise credentials_error from error


def require_roles(*roles: str):
    allowed_roles = set(roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return dependency


ROLE_PERMISSIONS = {
    "owner": {"*"},
    "fleet_manager": {"fleet", "maintenance", "compliance", "notifications"},
    "inventory_manager": {"inventory", "procurement", "workshop", "notifications"},
    "driver": {"driver", "fleet", "maintenance", "finance", "notifications"},
    "mechanic": {"maintenance", "workshop", "inventory", "notifications"},
    "technician": {"maintenance", "workshop", "inventory", "notifications"},
    "accountant": {"finance", "procurement", "notifications"},
}


def require_permission(permission: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        permissions = ROLE_PERMISSIONS.get(user.role, set())
        if "*" not in permissions and permission not in permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Role {user.role} cannot access {permission}")
        return user

    return dependency
