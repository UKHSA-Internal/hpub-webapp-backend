import logging

import numpy as np
from core.products.models import Product, ProductUpdate
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import OneHotEncoder

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize vectorizers and encoders
title_vectorizer = TfidfVectorizer()
program_name_vectorizer = TfidfVectorizer()
status_encoder = OneHotEncoder(sparse_output=False)
product_type_encoder = OneHotEncoder(sparse_output=False)
alternative_type_encoder = OneHotEncoder(sparse_output=False)

vectorizers_initialized = False
existing_product_types = set()
existing_alternative_types = set()


def get_expected_vector_size():
    """Calculate the total number of features expected in the final vector."""
    title_features = (
        len(title_vectorizer.get_feature_names_out())
        if title_vectorizer.vocabulary
        else 0
    )
    program_features = (
        len(program_name_vectorizer.get_feature_names_out())
        if program_name_vectorizer.vocabulary
        else 0
    )
    status_features = (
        len(getattr(status_encoder, "categories_", [])[0])
        if hasattr(status_encoder, "categories_")
        else 0
    )
    product_type_features = (
        len(getattr(product_type_encoder, "categories_", [])[0])
        if hasattr(product_type_encoder, "categories_")
        else 0
    )
    alternative_type_features = (
        len(getattr(alternative_type_encoder, "categories_", [])[0])
        if hasattr(alternative_type_encoder, "categories_")
        else 0
    )

    # Adding 3 for version_number, unit_of_measure, and maximum_order_quantity
    return (
        title_features
        + program_features
        + status_features
        + product_type_features
        + alternative_type_features
        + 3
    )


def initialize_vectorizers_and_encoders():
    global vectorizers_initialized, existing_product_types, existing_alternative_types

    # Query the database to get training data
    all_titles = [p.product_title for p in Product.objects.all() if p.product_title]
    all_program_names = [
        p.program_name for p in Product.objects.all() if p.program_name
    ]
    all_statuses = [[p.status] for p in Product.objects.all() if p.status]

    # Get distinct product and alternative types
    all_product_types = {
        p.product_type for p in ProductUpdate.objects.all() if p.product_type
    }
    all_alternative_types = {
        p.alternative_type for p in ProductUpdate.objects.all() if p.alternative_type
    }

    # Fit status encoder if it hasn't been fitted yet
    if not hasattr(status_encoder, "categories_"):
        status_encoder.fit(all_statuses)
    else:
        # Check if new statuses are present and re-fit if needed
        unique_statuses = set(status[0] for status in all_statuses)
        if not set(status_encoder.categories_[0]).issuperset(unique_statuses):
            status_encoder.fit(all_statuses)  # Refit encoder if new statuses found

    # Reinitialize encoders if new categories are detected
    if existing_product_types != all_product_types:
        product_type_encoder.fit([[ptype] for ptype in all_product_types])
        existing_product_types = all_product_types

    if existing_alternative_types != all_alternative_types:
        alternative_type_encoder.fit([[atype] for atype in all_alternative_types])
        existing_alternative_types = all_alternative_types

    # Fit the vectorizers only once
    if not vectorizers_initialized:
        title_vectorizer.fit(all_titles)
        program_name_vectorizer.fit(all_program_names)
        vectorizers_initialized = True


# Call this after initializing vectorizers
expected_vector_size = get_expected_vector_size()


def get_product_vector(product, product_update):
    """Generate a feature vector for a given product and product update."""
    initialize_vectorizers_and_encoders()

    # Validate required fields
    if not product.product_title or not product.program_name:
        logger.error(f"Missing data for product_code: {product.product_code}")
        return np.zeros((expected_vector_size,))

    # Extract feature values
    title = product.product_title or ""
    program_name = product.program_name or ""
    status = product.status or "unknown"
    description = (
        product_update.summary_of_guidance
        if product_update and product_update.summary_of_guidance
        else ""
    )
    file_url = product.file_url or ""

    # Vectorize the features
    title_vector = title_vectorizer.transform([title]).toarray().flatten()
    program_name_vector = (
        program_name_vectorizer.transform([program_name]).toarray().flatten()
    )
    status_vector = status_encoder.transform([[status]]).flatten()
    description_vector = title_vectorizer.transform([description]).toarray().flatten()
    file_url_vector = title_vectorizer.transform([file_url]).toarray().flatten()

    version_number_vector = np.array([product.version_number])
    unit_of_measure_vector = (
        np.array([product_update.unit_of_measure]) if product_update else np.array([0])
    )
    maximum_order_quantity_vector = (
        np.array([product_update.maximum_order_quantity])
        if product_update
        else np.array([0])
    )

    # Encoding product type and alternative type
    product_type_vector = (
        product_type_encoder.transform([[product_update.product_type]]).flatten()
        if product_update
        else np.zeros(len(product_type_encoder.categories_[0]))
    )
    alternative_type_vector = (
        alternative_type_encoder.transform(
            [[product_update.alternative_type]]
        ).flatten()
        if product_update
        else np.zeros(len(alternative_type_encoder.categories_[0]))
    )

    # Combine all vectors into a single feature vector
    feature_vector = np.concatenate(
        [
            title_vector,
            program_name_vector,
            status_vector,
            description_vector,
            file_url_vector,
            version_number_vector,
            unit_of_measure_vector,
            maximum_order_quantity_vector,
            product_type_vector,
            alternative_type_vector,
        ]
    )

    return feature_vector


def find_similar_products(
    target_product, product_update, top_n=5, similarity_threshold=0.80
):
    """Find products that are similar to the given target product."""
    initialize_vectorizers_and_encoders()

    # Get the feature vector for the target product
    target_vector = get_product_vector(target_product, product_update)

    # Retrieve all products except the target
    all_products = list(Product.objects.exclude(product_id=target_product.product_id))

    if not all_products:
        logger.warning(
            f"No similar products found for product_code: {target_product.product_code}"
        )
        return []

    # Compute feature vectors for all products
    product_vectors = np.array(
        [get_product_vector(product, product.update_ref) for product in all_products]
    )

    # Calculate cosine similarity between the target vector and all product vectors
    similarities = cosine_similarity([target_vector], product_vectors)[0]

    # Filter products based on similarity threshold
    filtered_indices = [
        i for i, score in enumerate(similarities) if score >= similarity_threshold
    ]

    # Get top N most similar products
    top_indices = sorted(filtered_indices, key=lambda i: similarities[i], reverse=True)[
        :top_n
    ]

    similar_products = []
    for idx in top_indices:
        similar_product = all_products[int(idx)]
        similar_products.append(
            {
                "product_title": similar_product.product_title,
                "product_code": similar_product.product_code,
                "similarity_score": similarities[idx],
            }
        )

    logger.info(
        f"Found {len(similar_products)} similar products for product_code: {target_product.product_code}"
    )
    return similar_products


#
