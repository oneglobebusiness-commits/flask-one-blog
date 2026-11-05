"""Shopify Admin GraphQL access."""
import logging
import mimetypes
import os
import re

import requests
from flask import current_app

from ..core import ApiError, db, oid
from .storage import find_local_image

log = logging.getLogger(__name__)
TIMEOUT = 30
SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")


def valid_shop(shop):
    return bool(shop) and bool(SHOP_RE.match(shop))


def get_integration(integration_id):
    integration = db().integrations.find_one({"_id": oid(integration_id, "Store")})
    if not integration:
        raise ApiError(404, "Store not found")
    if not integration.get("accessToken"):
        raise ApiError(409, "This store has not finished installing the app.")
    return integration


def graphql(integration, query, variables=None):
    version = current_app.config["SHOPIFY_API_VERSION"]
    url = f"https://{integration['storeUrl']}/admin/api/{version}/graphql.json"
    try:
        response = requests.post(
            url,
            json={"query": query, "variables": variables or {}},
            headers={"X-Shopify-Access-Token": integration["accessToken"]},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as err:
        log.warning("Shopify request failed: %s", err)
        raise ApiError(502, "The Shopify request failed.") from err
    if payload.get("errors") or payload.get("data") is None:
        log.warning("Shopify GraphQL errors: %s", payload.get("errors"))
        raise ApiError(502, "Shopify rejected the request.")
    return payload["data"]


def _check_user_errors(result):
    errors = result.get("userErrors") or []
    if errors:
        raise ApiError(502, ", ".join(e.get("message", "Shopify error") for e in errors))


def _search_term(search):
    return re.sub(r'[*:"\\()]', " ", search or "").strip()


def search_collections(integration_id, search="", first=20):
    integration = get_integration(integration_id)
    term = _search_term(search)
    data = graphql(
        integration,
        """query SearchCollections($first: Int!, $query: String!) {
          collections(first: $first, query: $query) {
            nodes { id title handle image { url } productsCount { count } }
          }
        }""",
        {"first": first, "query": f"title:*{term}*" if term else ""},
    )
    return {
        "success": True,
        "collections": [
            {
                "id": c["id"],
                "title": c["title"],
                "handle": c["handle"],
                "image": (c.get("image") or {}).get("url"),
                "productsCount": (c.get("productsCount") or {}).get("count", 0),
            }
            for c in data["collections"]["nodes"]
        ],
    }


PRODUCT_FIELDS = """id title handle status featuredImage { url }
  priceRangeV2 { minVariantPrice { amount currencyCode } }"""


def search_products(integration_id, search="", collection="", limit=10):
    integration = get_integration(integration_id)
    term = _search_term(search)
    if collection:
        data = graphql(
            integration,
            """query($id: ID!, $first: Int!) {
              collection(id: $id) { products(first: $first, sortKey: CREATED) { nodes { %s } } }
            }""" % PRODUCT_FIELDS,
            {"id": collection, "first": limit},
        )
        nodes = ((data.get("collection") or {}).get("products") or {}).get("nodes", [])
        if term:
            nodes = [n for n in nodes if term.lower() in (n.get("title") or "").lower()]
    else:
        data = graphql(
            integration,
            """query($query: String!, $first: Int!) {
              products(first: $first, query: $query, sortKey: CREATED_AT, reverse: true) { nodes { %s } }
            }""" % PRODUCT_FIELDS,
            {"query": f"title:*{term}*" if term else "", "first": limit},
        )
        nodes = data["products"]["nodes"]
    products = []
    for node in nodes:
        price = (node.get("priceRangeV2") or {}).get("minVariantPrice") or {}
        products.append(
            {
                "id": node["id"],
                "title": node["title"],
                "handle": node["handle"],
                "status": node.get("status"),
                "image": (node.get("featuredImage") or {}).get("url"),
                "price": price.get("amount"),
                "currency": price.get("currencyCode"),
            }
        )
    return products


def store_context(integration_id):
    integration = get_integration(integration_id)
    data = graphql(
        integration,
        """{
          shop { id name description primaryDomain { url } shipsToCountries }
          collections(first: 10) { nodes { id title description } }
          products(first: 20) { nodes { id title vendor productType tags } }
        }""",
    )
    products = data["products"]["nodes"]
    return {
        "shop": data["shop"],
        "collections": data["collections"]["nodes"],
        "totalCollections": len(data["collections"]["nodes"]),
        "totalProducts": len(products),
        "productTypes": sorted({p["productType"] for p in products if p.get("productType")}),
        "vendors": sorted({p["vendor"] for p in products if p.get("vendor")}),
        "tags": sorted({t for p in products for t in (p.get("tags") or [])}),
    }


def products_by_ids(integration_id, ids):
    if not ids:
        return []
    integration = get_integration(integration_id)
    data = graphql(
        integration,
        """query($ids: [ID!]!) { nodes(ids: $ids) { ... on Product {
          id title handle description vendor productType tags featuredImage { url }
          priceRangeV2 { minVariantPrice { amount currencyCode } }
        } } }""",
        {"ids": ids},
    )
    products = [n for n in data["nodes"] if n and n.get("handle")]
    for product in products:
        product["url"] = f"https://{integration['storeUrl']}/products/{product['handle']}"
    return products


def collections_by_ids(integration_id, ids):
    if not ids:
        return []
    integration = get_integration(integration_id)
    data = graphql(
        integration,
        """query($ids: [ID!]!) { nodes(ids: $ids) { ... on Collection {
          id title handle description seo { title description } image { url }
          products(first: 5) { nodes { id title handle vendor productType } }
        } } }""",
        {"ids": ids},
    )
    collections = [n for n in data["nodes"] if n and n.get("handle")]
    for collection in collections:
        collection["url"] = f"https://{integration['storeUrl']}/collections/{collection['handle']}"
        for product in (collection.get("products") or {}).get("nodes", []):
            product["url"] = f"https://{integration['storeUrl']}/products/{product['handle']}"
    return collections


def _get_or_create_blog(integration):
    data = graphql(integration, "{ blogs(first: 50) { nodes { id title handle } } }")
    blogs = data["blogs"]["nodes"]
    for wanted in ("news", "ai blog"):
        for blog in blogs:
            if blog["title"].lower() == wanted:
                return blog
    result = graphql(
        integration,
        """mutation($blog: BlogCreateInput!) {
          blogCreate(blog: $blog) { blog { id title handle } userErrors { field message } }
        }""",
        {"blog": {"title": "AI Blog"}},
    )["blogCreate"]
    _check_user_errors(result)
    return result["blog"]


def _upload_hero_image(integration, path):
    file_name = os.path.basename(path)
    mime = mimetypes.guess_type(file_name)[0] or "image/png"
    with open(path, "rb") as handle:
        content = handle.read()
    staged = graphql(
        integration,
        """mutation($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets { url resourceUrl parameters { name value } }
            userErrors { field message }
          }
        }""",
        {
            "input": [
                {
                    "filename": file_name,
                    "mimeType": mime,
                    "resource": "FILE",
                    "fileSize": str(len(content)),
                    "httpMethod": "POST",
                }
            ]
        },
    )["stagedUploadsCreate"]
    _check_user_errors(staged)
    target = staged["stagedTargets"][0]
    try:
        upload = requests.post(
            target["url"],
            data={p["name"]: p["value"] for p in target["parameters"]},
            files={"file": (file_name, content, mime)},
            timeout=120,
        )
        upload.raise_for_status()
    except requests.RequestException as err:
        raise ApiError(502, "Failed to upload the image to Shopify.") from err

    created = graphql(
        integration,
        """mutation($files: [FileCreateInput!]!) {
          fileCreate(files: $files) {
            files { ... on MediaImage { id } }
            userErrors { field message }
          }
        }""",
        {"files": [{"contentType": "IMAGE", "originalSource": target["resourceUrl"]}]},
    )["fileCreate"]
    _check_user_errors(created)
    media_id = (created.get("files") or [{}])[0].get("id")
    if not media_id:
        raise ApiError(502, "Shopify did not return a media id.")
    return _wait_for_media(integration, media_id)


def _wait_for_media(integration, media_id):
    import time

    for _ in range(10):
        node = graphql(
            integration,
            """query($id: ID!) { node(id: $id) { ... on MediaImage { fileStatus image { url } } } }""",
            {"id": media_id},
        ).get("node") or {}
        if node.get("fileStatus") == "READY" and (node.get("image") or {}).get("url"):
            return node["image"]["url"]
        time.sleep(1)
    raise ApiError(502, "Shopify image processing timed out.")


def _escape_attr(value):
    return (value or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _without_first_h1(html):
    """Shopify themes print the article title as the H1, so the body must not repeat it."""
    return re.sub(r"^\s*<h1\b[^>]*>.*?</h1>", "", html or "", count=1, flags=re.S | re.I)


def publish_blog(integration_id, blog):
    integration = get_integration(integration_id)
    shopify_blog = _get_or_create_blog(integration)

    hero = blog.get("heroImage") or {}
    local_image = find_local_image(hero)
    image_url = _upload_hero_image(integration, local_image) if local_image else hero.get("shopifyUrl")

    content = _without_first_h1(blog.get("content"))
    article = {
        "blogId": shopify_blog["id"],
        "title": blog["title"],
        "body": content,
        "isPublished": True,
        "tags": blog.get("keywords") or [],
        "author": {"name": "AI Writer"},
    }
    if blog.get("slug"):
        article["handle"] = blog["slug"]
    if blog.get("excerpt"):
        article["summary"] = blog["excerpt"]
    if image_url:
        article["image"] = {"url": image_url, "altText": blog["title"]}
        article["body"] = f'<img src="{_escape_attr(image_url)}" alt="{_escape_attr(blog["title"])}" />\n{content}'
    metafields = []
    for key, value in (("title_tag", blog.get("metaTitle")), ("description_tag", blog.get("metaDescription"))):
        if value:
            metafields.append(
                {"namespace": "global", "key": key, "type": "single_line_text_field", "value": value}
            )
    if metafields:
        article["metafields"] = metafields

    result = graphql(
        integration,
        """mutation($article: ArticleCreateInput!) {
          articleCreate(article: $article) {
            article { id handle publishedAt }
            userErrors { code field message }
          }
        }""",
        {"article": article},
    )["articleCreate"]
    _check_user_errors(result)
    created = result["article"]
    return {
        "blogId": shopify_blog["id"],
        "articleId": created["id"],
        "url": f"https://{integration['storeUrl']}/blogs/{shopify_blog['handle']}/{created['handle']}",
        "handle": created["handle"],
        "publishedAt": created.get("publishedAt"),
        "imageUrl": image_url,
    }
