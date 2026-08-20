/*
 * The profile ladder, once.
 *
 * Both the picker and the table on /standards read this. They ask different
 * questions of it -- "which one is mine" and "what are all of them" -- and if
 * each kept its own copy they would disagree within a month.
 *
 * `needs` is the part nobody else publishes. Every signing product lists the
 * profiles it supports; none of them mention that B-LT will not produce a file
 * at all until a trust folder and reachable revocation endpoints exist. The
 * env-var names are the server's own, from .env.example.
 */

export interface Profile {
  id: string;
  /** What this rung adds over the one below it. */
  adds: string;
  /** Empty means it signs with nothing configured. */
  needs: { what: string; key?: string }[];
  /** The thing you would only find out by trying it. */
  note: string;
  /** Whether it is the Indian variant of its rung. */
  india?: boolean;
}

const TSA = { what: 'A timestamp authority', key: 'TSA_URL' };
const CHAIN = { what: 'Your CA chain', key: 'TRUST_DIR' };
const REVOKE = { what: 'Reachable OCSP or CRL endpoints' };

export const profiles: Profile[] = [
  {
    id: 'B-B',
    adds: 'The signature, and nothing bolted on.',
    needs: [],
    note: 'Verifies while the certificate is valid. Once it expires, a checker can no longer tell whether it was valid at signing time.',
  },
  {
    id: 'B-T',
    adds: 'A trusted timestamp, per RFC 3161.',
    needs: [TSA],
    note: 'Five public authorities ship configured, DigiCert and Sectigo among them, with their roots included.',
  },
  {
    id: 'B-LT',
    adds: 'Revocation data embedded in the file, so it outlives the certificate.',
    needs: [TSA, CHAIN, REVOKE],
    note: 'The endpoints have to answer at signing time. If your CA’s OCSP is down this fails, rather than signing without the proof.',
  },
  {
    id: 'B-LTA',
    adds: 'An archival timestamp over the whole thing, so the chain can be re-timestamped.',
    needs: [TSA, CHAIN, REVOKE],
    note: 'The archival timestamp is what lets someone extend the proof in twenty years, before today’s algorithms get weak.',
  },
  {
    id: 'CCA-LTV',
    adds: 'The same revocation data, in the pdfRevocationInfoArchival attribute, per ESAIG 1.19.',
    needs: [CHAIN, REVOKE],
    note: 'No timestamp authority needed, which is the one thing it has over B-LT. Add one and you have CCA-LTA.',
    india: true,
  },
  {
    id: 'CCA-LTA',
    adds: 'CCA-LTV, plus a timestamp.',
    needs: [TSA, CHAIN, REVOKE],
    note: 'What the desktop app defaults to for Indian tokens, and what the ERPNext example uses.',
    india: true,
  },
];

export const byId = (id: string) => profiles.find((p) => p.id === id)!;

/*
 * The picker's one question. The axis is how long the signature has to keep
 * verifying, because that is what actually decides the answer -- and the first
 * two rungs do not vary by region, which is why `india` is absent on them and
 * the region toggle steps back when they are chosen.
 */
export interface Answer {
  slug: string;
  label: string;
  hint: string;
  any: string;
  india?: string;
}

export const answers: Answer[] = [
  {
    slug: 'today',
    label: 'Just today',
    hint: 'Someone opens it now and it checks out',
    any: 'B-B',
  },
  {
    slug: 'when',
    label: 'Prove when it was signed',
    hint: 'A trusted date on it',
    any: 'B-T',
  },
  {
    slug: 'after',
    label: 'After the certificate expires',
    hint: 'Still checks out years later',
    any: 'B-LT',
    india: 'CCA-LTV',
  },
  {
    slug: 'decades',
    label: 'For decades',
    hint: 'Archived, and still provable',
    any: 'B-LTA',
    india: 'CCA-LTA',
  },
];
