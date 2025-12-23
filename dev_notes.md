# Fixtures
```bash
docker compose exec web python manage.py loaddata fixtures/applications.json
docker compose exec web python manage.py assign_fixtures_owner --email maxpetrikin@gmail.com --from-user-id 1
```
```bash
docker compose exec web python manage.py assign_fixtures_owner --email maxpetrikin@gmail.com --from-user-id 1 --dry-run
```

---

# Migrations in Docker
```bash
docker compose exec web python manage.py makemigrations reports
docker compose exec web python manage.py migrate
```




