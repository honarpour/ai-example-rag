# Acme Cloud Corp. — Product FAQ

**What is Acme Cloud Corp.?**
Acme is a cloud object storage service for teams to store, sync, and share files across
devices. It offers automatic versioning, end-to-end encrypted sharing links, and
cross-platform sync clients for macOS, Windows, and Linux. Storage is billed per gigabyte
per month, with the first 15 GB free on every plan.

**What are the pricing tiers?**
Acme offers three tiers: Starter (15 GB free), Team ($8/user/month for 1 TB pooled
storage, shared across the team), and Business ($20/user/month for 5 TB pooled storage
plus admin controls, audit logs, and SSO integration). All tiers include unlimited
devices per user and unlimited file versioning for 30 days.

**How does file versioning work?**
Every time a file is modified and synced, Acme stores a new version rather than
overwriting the old one. Starter and Team plans retain the last 30 days of version
history; Business plans retain 180 days. Deleted files are recoverable from the trash for
the same retention window before being permanently purged.

**Is my data encrypted?**
Files are encrypted at rest using AES-256 and in transit using TLS 1.3. Shared links can
optionally be configured with end-to-end encryption, in which case Acme itself cannot
decrypt the file contents — only the sender and recipients holding the link's key can.
End-to-end encrypted links cannot be previewed in the browser, since Acme's servers
never see the unencrypted content.

**Can I integrate Acme with other tools?**
Yes. Acme provides a REST API and webhooks for file-upload and file-change events,
along with prebuilt integrations for Slack (share-link previews) and Google Workspace
(open-in-Acme from Docs/Sheets). Business plans additionally support SCIM for automated
user provisioning and deprovisioning from an identity provider.

**What happens if I exceed my storage limit?**
Accounts that exceed their plan's storage limit enter a 14-day grace period during which
uploads are blocked but downloads and sharing continue to work normally. After the grace
period, the account is placed in read-only mode until storage is reduced or the plan is
upgraded.
