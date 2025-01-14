from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def get_recommended_products(products):
    """
    Generate a list of recommended products based on title similarity.

    This function uses TF-IDF vectorization and cosine similarity to find
    similar products based on their titles. For each product, it identifies
    the top 3 most similar products, excluding the product itself, and
    compiles a list of unique recommended products.

    Args:
        products (list): A list of product objects, each with attributes
        'product_title' and 'product_code'.

    Returns:
        list: A list of dictionaries, each containing 'product_code' and
        'product_title' of recommended products.
    """

    # Gather product titles and codes for the similarity analysis
    product_titles = [product.product_title for product in products]

    # Create a TF-IDF Vectorizer for the product titles
    tfidf_vectorizer = TfidfVectorizer()
    tfidf_matrix = tfidf_vectorizer.fit_transform(product_titles)

    # Calculate cosine similarity between products
    cosine_sim = cosine_similarity(tfidf_matrix, tfidf_matrix)
    similar_indices = cosine_sim.argsort(axis=1)[:, -3:]

    # Collect recommended products, ensuring no duplicates
    recommended_products = set()
    for idx in range(len(products)):
        for similar_idx in similar_indices[idx]:
            similar_idx = int(similar_idx)
            if similar_idx != idx:
                recommended_product = products[similar_idx]
                recommended_products.add(
                    (
                        recommended_product.product_code,
                        recommended_product.product_title,
                    )
                )

    return [
        {"product_code": code, "product_title": title}
        for code, title in recommended_products
    ]
