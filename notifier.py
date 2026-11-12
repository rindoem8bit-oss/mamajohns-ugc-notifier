"""
Avisa num canal do Discord quando a loja (grupo ou conta) publica um UGC novo no Roblox.

Configuração (variáveis de ambiente / GitHub "Variables" e "Secrets"):
  DISCORD_WEBHOOK_URL  (secret)   URL do webhook do canal
  CREATOR_ID                      ID do grupo ou da conta dona da loja
  CREATOR_TYPE                    "group" (padrão) ou "user"
  DISCORD_ROLE_ID      (opcional) ID do cargo a marcar, ex.: @Drops
  STORE_NAME           (opcional) nome da loja, aparece no rodapé do aviso

Na primeira execução ele só memoriza os itens que já existem (não avisa nada),
para não lotar o canal com o catálogo inteiro.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
CREATOR_ID = (os.environ.get("CREATOR_ID") or "386673858").strip()  # grupo MamaJohns
CREATOR_TYPE = (os.environ.get("CREATOR_TYPE") or "group").strip().lower()
ROLE_ID = os.environ.get("DISCORD_ROLE_ID", "").strip()
STORE_NAME = (os.environ.get("STORE_NAME") or "MamaJohns").strip()
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_items.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (ugc-notifier)", "Accept": "application/json"}
EMBED_COLOR = 0x9B5CFF


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_items():
    """Lista os itens à venda do criador (até 5 páginas de 30)."""
    ctype = 2 if CREATOR_TYPE == "group" else 1
    base = (
        "https://catalog.roblox.com/v1/search/items/details"
        f"?CreatorType={ctype}&CreatorTargetId={CREATOR_ID}&Limit=30"
    )
    items, cursor = [], ""
    for _ in range(5):
        url = base + "&SortType=3" + (f"&Cursor={cursor}" if cursor else "")
        try:
            data = get_json(url)
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            # Se a ordenação não for aceita, busca sem ordenar
            data = get_json(base + (f"&Cursor={cursor}" if cursor else ""))
        items += data.get("data") or []
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
    return items


def thumbnail(item):
    try:
        if item.get("itemType") == "Bundle":
            url = f"https://thumbnails.roblox.com/v1/bundles/thumbnails?bundleIds={item['id']}&size=420x420&format=Png"
        else:
            url = f"https://thumbnails.roblox.com/v1/assets?assetIds={item['id']}&size=420x420&format=Png&isCircular=false"
        data = get_json(url).get("data") or []
        return data[0].get("imageUrl") if data else None
    except Exception:
        return None


def item_link(item):
    kind = "bundles" if item.get("itemType") == "Bundle" else "catalog"
    return f"https://www.roblox.com/{kind}/{item['id']}"


def post_discord(payload):
    body = json.dumps(payload).encode()
    for _ in range(3):
        req = urllib.request.Request(
            WEBHOOK, data=body, method="POST",
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=30).close()
            return
        except urllib.error.HTTPError as e:
            if e.code == 429:  # limite do Discord: espera e tenta de novo
                wait = json.load(e).get("retry_after", 2)
                time.sleep(float(wait) + 0.5)
                continue
            raise


def announce(item):
    price = item.get("price")
    if price is None:
        price = item.get("lowestPrice")
    embed = {
        "title": item.get("name", "Novo item"),
        "url": item_link(item),
        "color": EMBED_COLOR,
        "fields": [],
    }
    if price is not None:
        embed["fields"].append({"name": "Preço", "value": f"{price} Robux", "inline": True})
    desc = (item.get("description") or "").strip()
    if desc:
        embed["description"] = desc[:300] + ("…" if len(desc) > 300 else "")
    img = thumbnail(item)
    if img:
        embed["image"] = {"url": img}
    if STORE_NAME:
        embed["footer"] = {"text": STORE_NAME}

    content = "🆕 **Novo UGC na loja!**"
    allowed = {"parse": []}
    if ROLE_ID:
        content = f"<@&{ROLE_ID}> " + content
        allowed = {"roles": [ROLE_ID]}
    post_discord({"content": content, "embeds": [embed], "allowed_mentions": allowed})


def main():
    if not WEBHOOK or not CREATOR_ID:
        sys.exit("Faltou configurar DISCORD_WEBHOOK_URL e/ou CREATOR_ID.")

    items = fetch_items()
    key = lambda it: f"{it.get('itemType', 'Asset')}:{it['id']}"

    if not os.path.exists(STATE_FILE):
        seen = sorted(key(it) for it in items)
        with open(STATE_FILE, "w") as f:
            json.dump(seen, f, indent=0)
        print(f"Primeira execução: {len(seen)} itens memorizados, nenhum aviso enviado.")
        return

    with open(STATE_FILE) as f:
        seen = set(json.load(f))

    new = [it for it in items if key(it) not in seen]
    for it in reversed(new):  # do mais antigo para o mais novo
        announce(it)
        seen.add(key(it))
        print(f"Avisado: {it.get('name')} ({item_link(it)})")
        time.sleep(1.5)

    with open(STATE_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=0)
    print(f"{len(items)} itens conferidos, {len(new)} novos.")


if __name__ == "__main__":
    main()
