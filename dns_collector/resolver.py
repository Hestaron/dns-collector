"""DNS resolution for DnsCollector."""

import logging
from typing import NamedTuple

import dns.exception
import dns.resolver
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


class ResolveResult(NamedTuple):
    """Result of a single DNS resolution attempt."""

    status: str  # "ok" | "noanswer" | "nxdomain" | "timeout" | "error"
    records: list[tuple[str, int]]


@retry(
    retry=retry_if_exception_type((dns.exception.Timeout, dns.exception.DNSException)),
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=True,
)
def _query(
    res: dns.resolver.Resolver, domain: str, record_type: str
) -> dns.resolver.Answer:
    """Resolve with tenacity retry on transient DNS failures."""
    return res.resolve(domain, record_type)


def resolve(
    domain: str,
    record_type: str,
    timeout: float = 5.0,
    nameservers: list[str] | None = None,
) -> ResolveResult:
    """Resolve DNS records for a domain and record type.

    Returns a ResolveResult containing a status string and a list of
    (value, ttl) tuples.  The status distinguishes between successful
    resolution, missing records, and different failure modes.

    Transient failures (timeouts, generic DNS errors) are retried up to
    2 times via tenacity before returning a failure status.
    """
    res = dns.resolver.Resolver()
    res.lifetime = timeout
    if nameservers:
        res.nameservers = nameservers

    try:
        answers = _query(res, domain, record_type)
        rrset = answers.rrset
        assert rrset is not None, f"rrset missing for {record_type} {domain}"
        records = [(record.to_text(), rrset.ttl) for record in answers]
        return ResolveResult(status="ok", records=records)
    # Domain exists but not with that record_type, or no records at all
    except dns.resolver.NoAnswer:
        logger.debug(f"No {record_type} records found for {domain}")
        return ResolveResult(status="noanswer", records=[])
    # Domain does not exist at all
    except dns.resolver.NXDOMAIN:
        logger.warning(f"Domain does not exist: {domain}")
        return ResolveResult(status="nxdomain", records=[])
    # Timeout or other DNS errors, if a lot of timeouts, lifetime can be increased
    except dns.exception.Timeout:
        logger.warning(f"Timed out resolving {record_type} {domain}")
        return ResolveResult(status="timeout", records=[])
    # Parent class, so catches all other errors such as unexpected response, etc
    except dns.exception.DNSException as exc:
        logger.warning(f"DNS error for {record_type} {domain}: {exc}")
        return ResolveResult(status="error", records=[])
