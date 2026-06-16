import urllib.parse, requests, sys

sessionid = '15411850302%3ADAH6QBOk48Boz9%3A23%3AAYgM5JK_jJOtDJt86-sBNhOct_fWZmzTetRPiD5CYA'
decoded = urllib.parse.unquote(sessionid)
print('Testing session:', decoded[:30], '...')

resp = requests.get(
    'https://www.instagram.com/accounts/edit/',
    headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.5',
    },
    cookies={'sessionid': decoded},
    timeout=15,
    allow_redirects=False
)
print('Status:', resp.status_code)
if resp.status_code == 302:
    loc = resp.headers.get('Location', '')
    if 'login' in loc:
        print('RESULT: SESSION IS EXPIRED - need fresh sessionid from browser')
    else:
        print('Redirect to:', loc)
elif resp.status_code == 200:
    print('RESULT: SESSION IS VALID')
else:
    print('Response:', resp.text[:300])
