# Security and privacy

## Secrets

Never commit API keys, tokens, passwords, cookies, private endpoints, tenant identifiers, or connection strings. SerpAPI prototypes read `SERPAPI_API_KEY` from the environment.

If a credential is committed accidentally:

1. Revoke or rotate it immediately.
2. Remove it from Git history before sharing the repository.
3. Review access and provider logs.

## Candidate data

Resumes, contact details, application history, recruiter interactions, generated documents, and job exports are private data. Keep them outside Git in an access-controlled location.

## Internal and employer information

Do not add employer-confidential source, internal URLs, incident details, customer data, non-public scale figures, or proprietary implementation material. Public product documentation and independently written generic architecture are permitted.

## Reporting

Use the repository's private GitHub security reporting or contact the repository owner directly. Do not open a public issue containing sensitive data.
