/*
 * The dates and document numbers the prototypes show.
 *
 * Asia/Kolkata explicitly: the document is an Indian LLP's tax invoice and the
 * stamp says +05:30, so the clock has to be that one whatever machine is
 * reading it.
 */

const TZ = 'Asia/Kolkata';

const FORMAT = new Intl.DateTimeFormat('en-CA', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const partsOf = (d: Date) => {
  const p = FORMAT.formatToParts(d);
  const at = (type: string) => p.find((x) => x.type === type)!.value;
  return { y: at('year'), mo: at('month'), d: at('day'), h: at('hour'), mi: at('minute') };
};

/* What appearance.py writes under the mark. Takes a date because the signature
   is an event: the stamp should say when the reader pressed the button, not
   when the site was built. The build-time value below is the fallback for a
   reader with no JavaScript. */
export function signedAtFor(when: Date): string {
  const t = partsOf(when);
  return `${t.y}-${t.mo}-${t.d} ${t.h}:${t.mi} +05:30`;
}

const built = partsOf(new Date());

export const signedAt = signedAtFor(new Date());

/* The document's own identity, which is history rather than an event -- an
   invoice raised earlier in the year is what an invoice normally is, so these
   stay as of the build. */
export const year = built.y;
export const invoiceNo = `ACC-SINV-${year}-0412`;
export const folder = `~/Invoices/${year}-${built.mo}`;
export const invoiceFile = (n: number) => `invoice_${year}_04${n}.pdf`;
