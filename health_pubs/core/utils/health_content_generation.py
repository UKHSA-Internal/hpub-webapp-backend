import openai

# Azure OpenAI Configuration
endpoint = "https://datastudioopenai.openai.azure.com/"
deployment_name = "datamodeller"
api_key = "97ff1dd8a91c44aa94af45a603808edd"
api_version = "2024-08-01-preview"

# Configure the openai library for Azure OpenAI
openai.api_base = endpoint
openai.api_key = api_key
openai.api_type = "azure"
openai.api_version = api_version


def generate_health_content(topic, user_inquiry=None):
    """
    Generate a detailed health article using Azure OpenAI.

    Args:
        topic (str): The health topic to write about.
        user_inquiry (str, optional): A specific question to address in the content.

    Returns:
        str: Generated health article.
    """
    # Create the base prompt
    prompt = (
        f"Write a detailed health publication on {topic}. "
        "The article should include the following sections:\n"
        "1. Introduction: Overview of the topic.\n"
        "2. Benefits: Explain the benefits of vaccination.\n"
        "3. Risks: Mention any potential side effects or risks.\n"
        "4. Guidelines: Provide current vaccination guidelines.\n"
        "5. Conclusion: Summarize the key points.\n"
    )

    # Add the user inquiry to the prompt if provided
    if user_inquiry:
        prompt += f"Answer this specific question: {user_inquiry}."

    # Calling Azure OpenAI to generate the content
    response = openai.ChatCompletion.create(
        deployment_id=deployment_name,
        messages=[
            {"role": "system", "content": "You are an expert health content writer."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
        temperature=0.7,
        top_p=0.95,
        frequency_penalty=0.1,
        presence_penalty=0.1,
    )

    # Extract and return the generated content
    return response["choices"][0]["message"]["content"]


# Example usage
topic = "Hepatitis Vaccination"
user_inquiry = "What are the long-term effects of hepatitis vaccination?"
draft = generate_health_content(topic, user_inquiry)

print("Draft:\n", draft)
