/*
 * The dates and document numbers the prototypes show.
 *
 * Derived at build time rather than typed in, so a page built today does not
 * claim a signature from a year that has passed. The site is static, so these
 * are as current as the last deploy.
 *
 * Asia/Kolkata explicitly: the document is an Indian LLP's tax invoice and the
 * stamp says +05:30, so the clock has to be that one whatever the build machine
 * is set to.
 */

const TZ = 'Asia/Kolkata';

const parts = new Intl.DateTimeFormat('en-CA', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
}).formatToParts(new Date());

const at = (type: string) => parts.find((p) => p.type === type)!.value;

export const year = at('year');

/* What appearance.py writes under the mark. */
export const signedAt = `${year}-${at('month')}-${at('day')} ${at('hour')}:${at('minute')} +05:30`;

/* ERPNext's own naming series for a submitted Sales Invoice. */
export const invoiceNo = `ACC-SINV-${year}-0412`;

/* The folder the desktop app is pointed at, and what is in it. */
export const folder = `~/Invoices/${year}-${at('month')}`;
export const invoiceFile = (n: number) => `invoice_${year}_04${n}.pdf`;
