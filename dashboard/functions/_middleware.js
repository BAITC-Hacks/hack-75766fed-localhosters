// Закрывает весь сайт на Cloudflare Pages паролем (Basic Auth): в data/ лежат SCADA организаторов и наш сабмит.
// Пароль — секрет проекта DASH_PASSWORD (wrangler pages secret put). Без секрета сайт не открывается (fail closed).
const USER = 'localhosters';

function unauthorized() {
  return new Response('Windagent: нужен пароль команды Localhosters', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Windagent", charset="UTF-8"',
      'Cache-Control': 'no-store',
      'X-Robots-Tag': 'noindex, nofollow',
    },
  });
}

function safeEqual(a, b) {
  const x = new TextEncoder().encode(a), y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

export async function onRequest({ request, env, next }) {
  const expected = env.DASH_PASSWORD;
  if (!expected) return unauthorized();
  const header = request.headers.get('Authorization') || '';
  if (!header.startsWith('Basic ')) return unauthorized();
  let decoded = '';
  try { decoded = new TextDecoder().decode(Uint8Array.from(atob(header.slice(6)), c => c.charCodeAt(0))); } catch { return unauthorized(); }
  const sep = decoded.indexOf(':');
  if (sep < 0 || decoded.slice(0, sep) !== USER || !safeEqual(decoded.slice(sep + 1), expected)) return unauthorized();
  const response = await next();
  const out = new Response(response.body, response);
  out.headers.set('X-Robots-Tag', 'noindex, nofollow');
  out.headers.set('Cache-Control', 'private, no-store');
  return out;
}
