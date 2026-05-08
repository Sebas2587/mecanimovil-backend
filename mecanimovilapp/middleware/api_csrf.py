class ApiCsrfExemptMiddleware:
    """
    Bypass CSRF checks for all /api/* endpoints.

    The REST API uses Token authentication — not session/cookie auth — so
    Django's CsrfViewMiddleware adds no security benefit here and blocks
    legitimate cross-origin POST requests from the web client.

    Sets request.csrf_processing_done = True (first check in process_view)
    so the middleware skips validation entirely for /api/ paths.
    Django admin and any non-/api/ route keep their normal CSRF flow.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/'):
            # process_view checks this flag first → returns None (allow) immediately
            request.csrf_processing_done = True
        return self.get_response(request)
