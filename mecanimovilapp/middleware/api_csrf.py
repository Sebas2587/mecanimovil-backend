class ApiCsrfExemptMiddleware:
    """
    Bypass CSRF checks for all /api/* endpoints.

    The REST API uses Token authentication — not session/cookie auth — so
    Django's CsrfViewMiddleware adds no security benefit for those routes and
    blocks legitimate cross-origin POST requests from the web client.

    Django admin and any non-API route still go through the normal CSRF flow.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/'):
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)
