import time
from typing import Tuple

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

REQUESTS = Counter(
    "quetz_requests_total",
    "Total count of requests by method and path.",
    ["method", "path_template"],
)
RESPONSES = Counter(
    "quetz_responses_total",
    "Total count of responses by method, path and status codes.",
    ["method", "path_template", "status_code"],
)
REQUESTS_PROCESSING_TIME = Histogram(
    "quetz_requests_processing_time_seconds",
    "Histogram of requests processing time by path (in seconds)",
    ["method", "path_template"],
)
EXCEPTIONS = Counter(
    "quetz_exceptions_total",
    "Total count of exceptions raised by path and exception type",
    ["method", "path_template", "exception_type"],
)
REQUESTS_IN_PROGRESS = Gauge(
    "quetz_requests_in_progress",
    "Gauge of requests by method and path currently being processed",
    ["method", "path_template"],
)
DOWNLOAD_COUNT = Counter(
    "download_count",
    "Total count of package downloads",
    ["channel", "platform", "package_name", "version", "package_type"],
)
UPLOAD_COUNT = Counter(
    "upload_count",
    "Total count of package uploads",
    ["channel", "platform", "package_name", "version", "package_type"],
)

DATABASE_POOL_SIZE = Gauge(
    "database_pool_size", "number of opened database connections"
)

DATABASE_CONNECTIONS_USED = Gauge(
    "database_connections_used", "number of used database connections"
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, filter_unhandled_paths: bool = False) -> None:
        super().__init__(app)
        self.filter_unhandled_paths = filter_unhandled_paths

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        method = request.method
        path_template, is_handled_path = self.get_path_template(request)

        if self._is_path_filtered(is_handled_path):
            return await call_next(request)

        REQUESTS_IN_PROGRESS.labels(method=method, path_template=path_template).inc()
        REQUESTS.labels(method=method, path_template=path_template).inc()

        try:
            before_time = time.perf_counter()
            response = await call_next(request)
            after_time = time.perf_counter()
        except Exception as e:
            EXCEPTIONS.labels(
                method=method,
                path_template=path_template,
                exception_type=type(e).__name__,
            ).inc()
            raise e from None
        else:
            REQUESTS_PROCESSING_TIME.labels(
                method=method, path_template=path_template
            ).observe(after_time - before_time)
            RESPONSES.labels(
                method=method,
                path_template=path_template,
                status_code=response.status_code,
            ).inc()
        finally:
            REQUESTS_IN_PROGRESS.labels(
                method=method, path_template=path_template
            ).dec()

        return response

    @staticmethod
    def get_path_template(request: Request) -> Tuple[str, bool]:
        for route in request.app.routes:
            match, child_scope = route.matches(request.scope)
            if match == Match.FULL:
                return route.path, True

        return request.url.path, False

    def _is_path_filtered(self, is_handled_path: bool) -> bool:
        return self.filter_unhandled_paths and not is_handled_path
