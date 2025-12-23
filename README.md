---

## Fixtures (dev testdata)

1. Upload fixtures into the Docker test DB `(replace you-google-email@gmail.com)`
```bash
# upload testdata + move to your account
docker compose exec web python manage.py loaddata fixtures/applications.json \
  && docker compose exec web python manage.py assign_fixtures_owner --email you-google-email@gmail.com --from-user-id 1
```
2. Verify fixtures are assigned to your account (dry-run)
```bash
# check record in your account (dry-run)
docker compose exec web python manage.py assign_fixtures_owner --email you-google-email@gmail.com --from-user-id 1 --dry-run
```

---