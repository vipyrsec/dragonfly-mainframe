from fastapi import HTTPException, status


class BadCredentialsException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail="Bad credentials")


class PermissionDeniedException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, detail="Permission denied")


class RequiresAuthenticationException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail="Requires authentication")


class UnableCredentialsException(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to verify credentials")
