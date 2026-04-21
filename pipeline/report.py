from models import PartnerState, PartnerStatus

_STATUS_LABEL = {
    PartnerStatus.RESOLVED: "RESOLVED",
    PartnerStatus.PARTIALLY_RESOLVED: "PARTIALLY RESOLVED",
    PartnerStatus.UNRESOLVED: "UNRESOLVED",
    PartnerStatus.NO_EMAIL: "BLOCKED — NO EMAIL",
    PartnerStatus.NO_RESPONSE: "NO RESPONSE",
    PartnerStatus.OUTREACH_READY: "OUTREACH SENT",
}


def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def print_report(partners: list[PartnerState]) -> None:
    _section("TRADING PARTNER DATA COLLECTION — FINAL REPORT")

    for partner in partners:
        label = _STATUS_LABEL.get(partner.status, partner.status.value.upper())
        print(f"\n  {partner.name}  [{label}]")

        if partner.status == PartnerStatus.RESOLVED:
            print("    ✓ All required fields present and valid.")

        elif partner.status == PartnerStatus.NO_EMAIL:
            print("    ✗ Cannot send outreach — no valid email address on file.")
            for issue in partner.issues:
                if issue.field != "email":
                    print(f"    ✗ {issue}")

        elif partner.status == PartnerStatus.NO_RESPONSE:
            print("    ⚠ No reply received. Outstanding fields:")
            for issue in partner.issues:
                print(f"    ✗ {issue}")

        elif partner.status == PartnerStatus.PARTIALLY_RESOLVED:
            resolved_fields = partner.problem_fields - {i.field for i in partner.remaining_issues}
            print("    Fields resolved after response:")
            for f in sorted(resolved_fields):
                print(f"    ✓ {f}: {getattr(partner, f)}")
            print("    Fields still unresolved:")
            for issue in partner.remaining_issues:
                print(f"    ✗ {issue}")

        elif partner.status == PartnerStatus.UNRESOLVED:
            print("    Response received but no usable data extracted. Still missing:")
            for issue in partner.remaining_issues:
                print(f"    ✗ {issue}")

    _section("SUMMARY")
    counts = {s: sum(1 for p in partners if p.status == s) for s in PartnerStatus}
    total = len(partners)
    print(f"  Total partners:       {total}")
    print(f"  Fully resolved:       {counts[PartnerStatus.RESOLVED]}")
    print(f"  Partially resolved:   {counts[PartnerStatus.PARTIALLY_RESOLVED]}")
    print(f"  Unresolved:           {counts[PartnerStatus.UNRESOLVED]}")
    print(f"  No response:          {counts[PartnerStatus.NO_RESPONSE]}")
    print(f"  Blocked (no email):   {counts[PartnerStatus.NO_EMAIL]}")
    print()
