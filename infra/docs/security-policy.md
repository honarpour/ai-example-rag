# Acme Cloud Corp. — Data Security & Access Policy

All employees must use company-issued devices with full-disk encryption and an approved
endpoint security agent for any work involving customer data. Personal devices may only
be used to access email and chat, never customer file contents or internal source code
repositories.

Access to production systems follows the principle of least privilege. Engineers are
granted read access to production logs and metrics by default; write access to production
databases or the ability to deploy requires manager approval and is reviewed quarterly.
All production access is logged and retained for 1 year for audit purposes.

Multi-factor authentication (MFA) is required for all internal tools, including email,
the VPN, and the internal admin dashboard. Hardware security keys are provided to
engineers with production database access; all other employees may use an authenticator
app. SMS-based MFA is not permitted for any system that touches customer data.

Customer data must never be copied to a personal device, personal cloud storage account,
or removable media. When debugging a customer-reported issue requires inspecting real
customer data, engineers must use the sandboxed internal debugging tool, which logs every
record accessed and automatically expires access after 4 hours.

Any suspected security incident — a lost device, a phishing attempt that was clicked, or
unusual account activity — must be reported to security@acmecloud.example within 1 hour
of discovery, regardless of time of day. Do not attempt to investigate or remediate a
suspected breach yourself; the security team will coordinate the response.

All employees complete annual security awareness training, and engineers with production
access complete an additional secure-coding training module every 12 months. Failure to
complete required training within the grace period results in automatic suspension of
production access until training is finished.
