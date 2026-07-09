import urllib.request, urllib.error

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

opener = urllib.request.build_opener(NoRedirect)
try:
    r = opener.open('http://www.baidu.com', timeout=8)
    print('direct access, status:', r.status)
    print('url:', r.url)
except urllib.error.HTTPError as e:
    print('redirect:', e.code, e.headers.get('Location',''))
except Exception as e:
    print('err:', type(e).__name__, e)
