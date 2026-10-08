# Family sharing report — 2026-10-08

## Verified cause

Read-only inspection of the reported accounts found two separate one-member
families and no accepted invitation. One account had four active products at the
first inspection; at the second inspection they were all marked purchased.
No family-registry versus shopping-store membership divergence was found.

Creating a family or generating its invitation does not add another person. The
recipient must open the invitation and explicitly confirm joining. Previously the
shopping header claimed the list was shared even for a one-member family, making
an incomplete invitation look like a synchronisation failure.

## Change

The shopping API exposes current member count. Mini App shows the count beside
Family and labels a one-member list accordingly. Bot and family dialog explain
that joining requires confirmation; active invitations are labelled awaiting
acceptance. No production accounts were merged and no user data was moved.

## Regression

Two users each create their own family, then accept an invitation through the real
HTTP API. The partner adds products; the creator sees the same active products and
both see a subsequent purchase. Member count changes from one to two only after
acceptance. This test passes along with the complete 64-test suite.

## Remaining action

For the reported couple, the empty-family account should accept an invitation from
the account that already has the product catalog. That preserves the destination
catalog and avoids transferring only the active list from a retired source family.
They must confirm this themselves; opening a link without confirmation leaves the
accounts in separate families. No claim is made that the exact missed click or
onboarding step was reconstructed from telemetry, which does not retain messages.
