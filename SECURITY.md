# Security and privacy

Never publish API keys, production configuration, databases, state, review queues, reading titles, or unreviewed logs. Each reader's Kavita key lives in a private file—never in command arguments, URLs, or Git. Authenticated requests do not follow redirects. Use HTTPS, or a controlled private network only when explicitly enabling the private-IP HTTP exception.

The connector writes through Yamtrack's ORM, not direct SQL. Applying changes requires write access to the database and state directory. The review panel shares Yamtrack's session and secret; never expose its port directly. Do not disable CSRF or grant broad permissions to work around errors.

External catalogs receive bibliographic queries. Review their policies before enabling matching for sensitive libraries. The state file may reveal reading habits and usernames even though it contains no API keys.

For vulnerabilities, use GitHub's private **Report a vulnerability** channel when available. Do not open a public issue containing exploitable details or secrets. If private reporting is unavailable, request a private contact without disclosing the vulnerability itself.

Compatibility is limited to the documented versions. Every Yamtrack or Kavita upgrade requires revalidation and consistent backups.
