# Contributing

1. Create a virtualenv with Python 3.12 and run `make install`.
2. Run `make lint` and `make test` before opening a pull request.
3. Add tests with behaviour changes, especially for ingestion, versioning and access control.
4. Keep documentation in sync with the code. Do not document features that do not exist.
5. Never commit real documents, credentials or `.env` files.

Index adapters (Qdrant, OpenSearch) have extra tests that need running services:
`make up && make test-integration`.
