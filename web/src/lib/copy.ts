/**
 * UI copy for every enum (SPEC §14 copy table, §21 trust wording).
 *
 * Never render a raw enum value — always go through these maps (or `enumLabel`). Every entry has
 * a human label, a lucide icon and a colour tone. `assertNoRawEnums` is used by tests to make sure
 * rendered text never leaks values like `needs_review` or `tax_assessment`.
 */
import type { LucideIcon } from "lucide-react";
import {
  ArrowDownLeft,
  AlarmClock,
  Award,
  BadgeAlert,
  Banknote,
  Bell,
  BookOpen,
  Briefcase,
  Building,
  CalendarClock,
  CalendarX,
  CircleCheck,
  CircleCheckBig,
  CircleDashed,
  CircleX,
  Clock,
  CloudUpload,
  Dumbbell,
  Euro,
  FileCheckCorner,
  FilePen,
  FilePenLine,
  FileText,
  FileX,
  Flag,
  Folder,
  GraduationCap,
  HandCoins,
  Handshake,
  HeartPulse,
  Hourglass,
  House,
  IdCard,
  Info,
  Landmark,
  Lightbulb,
  ListTodo,
  LoaderCircle,
  Mail,
  Milestone,
  TreePalm,
  PiggyBank,
  Radio,
  Receipt,
  ReceiptText,
  Scale,
  ScanText,
  Send,
  Shield,
  ShieldAlert,
  ShieldPlus,
  Signature,
  Smartphone,
  Sparkles,
  Stamp,
  Stethoscope,
  Store,
  TramFront,
  TrendingUp,
  TriangleAlert,
  User,
  UserRound,
  Users,
  Wallet,
  Wifi,
  Zap,
  Tv,
  Globe,
  Printer,
  MonitorSmartphone,
  MousePointerClick,
  ScrollText,
  Recycle,
  Repeat,
} from "lucide-react";
import {
  AREAS,
  AREA_STATUSES,
  CONFIDENCES,
  CONTRACT_CATEGORIES,
  CONTRACT_REGIMES,
  CONTRACT_STATUSES,
  COST_INTERVALS,
  DIRECTIONS,
  DOCUMENT_KINDS,
  DOCUMENT_STATUSES,
  DRAFT_KINDS,
  DRAFT_STATUSES,
  GROUNDINGS,
  ITEM_KINDS,
  ITEM_STATUSES,
  JOB_STAGES,
  LANE_BAR_KINDS,
  LANE_BAR_STATUSES,
  MARKER_KINDS,
  NOTICE_BASES,
  PARTY_KINDS,
  PRIORITIES,
  REMEDY_TYPES,
  SEND_CHANNELS,
  SEND_FORMS,
  SUGGESTION_KINDS,
  SUGGESTION_STATUSES,
  TIMELINE_TYPES,
  type Area,
  type AreaStatusLevel,
  type Confidence,
  type ContractCategory,
  type ContractRegime,
  type ContractStatus,
  type CostInterval,
  type Direction,
  type DocumentKind,
  type DocumentStatus,
  type DraftKind,
  type DraftStatus,
  type Grounding,
  type ItemKind,
  type ItemStatus,
  type JobStage,
  type LaneBarKind,
  type LaneBarStatus,
  type MarkerKind,
  type NoticeBasis,
  type PartyKind,
  type Priority,
  type RemedyType,
  type SendChannelKind,
  type SendForm,
  type SuggestionKind,
  type SuggestionStatus,
  type TimelineType,
} from "@/api/types";

// ------------------------------------------------------------------------------------------------
// Tones → Tailwind classes (full literal class names so Tailwind can see them)
//
// Categories (letter kinds, life areas, organisations, contract categories) are not alarms: they
// never take a status tone (danger / warn) or the deadline tone. How urgent something is shows in
// its date (Countdown) and status, so a "Fine" chip or the Health area never looks like an error.
// ------------------------------------------------------------------------------------------------

export type Tone =
  | "deadline"
  | "payment"
  | "appointment"
  | "task"
  | "expiry"
  | "contract"
  | "document"
  | "milestone"
  | "ok"
  | "warn"
  | "danger"
  | "accent"
  | "neutral";

export interface ToneClasses {
  /** readable text on the soft background or on surfaces (AA) */
  text: string;
  /** icon / accent colour (≥ 3:1 non-text contrast) */
  icon: string;
  /** soft tinted background */
  soft: string;
  /** solid fill (dots, bars) */
  solid: string;
  /** subtle border */
  border: string;
}

export const TONES: Record<Tone, ToneClasses> = {
  deadline: { text: "text-k-deadline-ink", icon: "text-k-deadline", soft: "bg-k-deadline-soft", solid: "bg-k-deadline", border: "border-k-deadline/25" },
  payment: { text: "text-k-payment-ink", icon: "text-k-payment", soft: "bg-k-payment-soft", solid: "bg-k-payment", border: "border-k-payment/25" },
  appointment: { text: "text-k-appointment-ink", icon: "text-k-appointment", soft: "bg-k-appointment-soft", solid: "bg-k-appointment", border: "border-k-appointment/25" },
  task: { text: "text-k-task-ink", icon: "text-k-task", soft: "bg-k-task-soft", solid: "bg-k-task", border: "border-k-task/25" },
  expiry: { text: "text-k-expiry-ink", icon: "text-k-expiry", soft: "bg-k-expiry-soft", solid: "bg-k-expiry", border: "border-k-expiry/25" },
  contract: { text: "text-k-contract-ink", icon: "text-k-contract", soft: "bg-k-contract-soft", solid: "bg-k-contract", border: "border-k-contract/25" },
  document: { text: "text-k-document-ink", icon: "text-k-document", soft: "bg-k-document-soft", solid: "bg-k-document", border: "border-k-document/25" },
  milestone: { text: "text-k-milestone-ink", icon: "text-k-milestone", soft: "bg-k-milestone-soft", solid: "bg-k-milestone", border: "border-k-milestone/25" },
  ok: { text: "text-ok-ink", icon: "text-ok", soft: "bg-ok-soft", solid: "bg-ok", border: "border-ok/25" },
  warn: { text: "text-warn-ink", icon: "text-warn", soft: "bg-warn-soft", solid: "bg-warn", border: "border-warn/30" },
  danger: { text: "text-danger-ink", icon: "text-danger", soft: "bg-danger-soft", solid: "bg-danger", border: "border-danger/25" },
  accent: { text: "text-accent", icon: "text-accent", soft: "bg-accent-soft", solid: "bg-accent", border: "border-accent/25" },
  neutral: { text: "text-muted", icon: "text-muted", soft: "bg-surface-2", solid: "bg-faint", border: "border-line" },
};

export interface EnumCopy {
  label: string;
  icon: LucideIcon;
  tone: Tone;
  /** optional one-line explanation (tooltips, filters) */
  hint?: string;
}

type CopyMap<K extends string> = Record<K, EnumCopy>;

// ------------------------------------------------------------------------------------------------
// Documents
// ------------------------------------------------------------------------------------------------

export const DOCUMENT_KIND_COPY: CopyMap<DocumentKind> = {
  tax_assessment: { label: "Tax assessment", icon: Landmark, tone: "expiry" },
  tax_letter: { label: "Tax office letter", icon: Landmark, tone: "expiry" },
  authority_letter: { label: "Letter from an authority", icon: Building, tone: "milestone" },
  residence_permit: { label: "Residence permit", icon: IdCard, tone: "expiry" },
  social_insurance: { label: "Social insurance", icon: ShieldPlus, tone: "milestone" },
  health_insurance: { label: "Health insurance", icon: HeartPulse, tone: "appointment" },
  invoice: { label: "Invoice", icon: Receipt, tone: "payment" },
  dunning: { label: "Payment reminder", icon: BadgeAlert, tone: "payment" },
  contract: { label: "Contract", icon: Signature, tone: "contract" },
  contract_change: { label: "Contract change", icon: FilePenLine, tone: "contract" },
  price_increase: { label: "Price increase", icon: TrendingUp, tone: "payment" },
  cancellation_confirmation: { label: "Cancellation confirmed", icon: FileX, tone: "contract" },
  payslip: { label: "Payslip", icon: Wallet, tone: "task" },
  bank_letter: { label: "Bank letter", icon: Banknote, tone: "document" },
  insurance: { label: "Insurance", icon: Shield, tone: "contract" },
  rent_lease: { label: "Rent & flat", icon: House, tone: "contract" },
  utility_bill: { label: "Utility bill", icon: Zap, tone: "payment" },
  university: { label: "University", icon: GraduationCap, tone: "milestone" },
  employment: { label: "Work", icon: Briefcase, tone: "task" },
  appointment: { label: "Appointment", icon: CalendarClock, tone: "appointment" },
  fine: { label: "Fine", icon: Scale, tone: "payment" },
  receipt: { label: "Receipt", icon: ReceiptText, tone: "document" },
  identity_document: { label: "ID document", icon: IdCard, tone: "expiry" },
  broadcasting_fee: { label: "Broadcasting fee", icon: Radio, tone: "payment" },
  certificate: { label: "Certificate", icon: Award, tone: "milestone" },
  personal: { label: "Personal", icon: User, tone: "document" },
  other: { label: "Other letter", icon: FileText, tone: "document" },
};

export const DOCUMENT_STATUS_COPY: CopyMap<DocumentStatus> = {
  queued: { label: "Waiting to be read", icon: Clock, tone: "neutral" },
  processing: { label: "Reading…", icon: LoaderCircle, tone: "accent" },
  processed: { label: "Filed", icon: CircleCheck, tone: "ok" },
  needs_review: { label: "Please check", icon: TriangleAlert, tone: "warn", hint: "Something in this letter needs a quick look from you." },
  failed: { label: "Couldn't read", icon: CircleX, tone: "danger" },
};

export const DIRECTION_COPY: CopyMap<Direction> = {
  incoming: { label: "Received", icon: Mail, tone: "neutral" },
  outgoing: { label: "Sent by you", icon: Send, tone: "accent" },
  note: { label: "Note", icon: FilePen, tone: "neutral" },
};

/** Evidence grounding (SPEC §21: never say "verified"). */
export const GROUNDING_COPY: CopyMap<Grounding> = {
  verified: { label: "Found in the letter", icon: CircleCheck, tone: "ok", hint: "The exact sentence was found on the page, digits included." },
  model_read: { label: "Read by AI from the photo", icon: ScanText, tone: "accent", hint: "There was no text layer, so Claude transcribed the image. Worth a glance." },
  unverified: { label: "Couldn't find this — please check", icon: TriangleAlert, tone: "warn", hint: "We could not locate this sentence in the letter." },
  user: { label: "Confirmed by you", icon: CircleCheckBig, tone: "ok" },
};

// ------------------------------------------------------------------------------------------------
// To-dos & dates
// ------------------------------------------------------------------------------------------------

export const ITEM_KIND_COPY: CopyMap<ItemKind> = {
  deadline: { label: "Deadline", icon: Hourglass, tone: "deadline" },
  payment: { label: "Payment", icon: Euro, tone: "payment" },
  appointment: { label: "Appointment", icon: CalendarClock, tone: "appointment" },
  task: { label: "To-do", icon: ListTodo, tone: "task" },
  expiry: { label: "Expires", icon: CalendarX, tone: "expiry" },
  reminder: { label: "Reminder", icon: Bell, tone: "task" },
  milestone: { label: "Milestone", icon: Milestone, tone: "milestone" },
};

/** A payment that comes to you (salary, stipend, a tax refund): money in, not a bill to pay. */
export const MONEY_IN_COPY: EnumCopy = { label: "Money in", icon: ArrowDownLeft, tone: "ok" };

export const ITEM_STATUS_COPY: CopyMap<ItemStatus> = {
  open: { label: "Open", icon: CircleDashed, tone: "neutral" },
  done: { label: "Done", icon: CircleCheck, tone: "ok" },
  dismissed: { label: "Dismissed", icon: CircleX, tone: "neutral" },
  snoozed: { label: "Snoozed", icon: AlarmClock, tone: "neutral" },
  missed: { label: "Missed", icon: TriangleAlert, tone: "danger" },
};

export const PRIORITY_COPY: CopyMap<Priority> = {
  low: { label: "Low", icon: Flag, tone: "neutral" },
  normal: { label: "Normal", icon: Flag, tone: "neutral" },
  high: { label: "Important", icon: Flag, tone: "warn" },
  critical: { label: "Urgent", icon: Flag, tone: "danger" },
};

export const AREA_COPY: CopyMap<Area> = {
  home: { label: "Home", icon: House, tone: "contract" },
  work: { label: "Work", icon: Briefcase, tone: "task" },
  study: { label: "Study", icon: GraduationCap, tone: "milestone" },
  health: { label: "Health", icon: HeartPulse, tone: "appointment" },
  money: { label: "Money", icon: Wallet, tone: "payment" },
  residence: { label: "Residence", icon: Stamp, tone: "expiry" },
  tax: { label: "Tax", icon: Landmark, tone: "expiry" },
  mobility: { label: "Getting around", icon: TramFront, tone: "appointment" },
  insurance: { label: "Insurance", icon: Shield, tone: "contract" },
  leisure: { label: "Leisure", icon: TreePalm, tone: "ok" },
  family: { label: "Family", icon: Users, tone: "appointment" },
  other: { label: "Other", icon: Folder, tone: "neutral" },
};

export const AREA_STATUS_COPY: CopyMap<AreaStatusLevel> = {
  ok: { label: "All good", icon: CircleCheck, tone: "ok" },
  attention: { label: "Needs attention", icon: Info, tone: "warn" },
  urgent: { label: "Urgent", icon: TriangleAlert, tone: "danger" },
};

export const TIMELINE_TYPE_COPY: CopyMap<TimelineType> = {
  document: { label: "Letter", icon: Mail, tone: "document" },
  deadline: ITEM_KIND_COPY.deadline,
  payment: ITEM_KIND_COPY.payment,
  appointment: ITEM_KIND_COPY.appointment,
  task: ITEM_KIND_COPY.task,
  expiry: ITEM_KIND_COPY.expiry,
  contract: { label: "Contract", icon: Signature, tone: "contract" },
  draft: { label: "Your letter", icon: Send, tone: "accent" },
  milestone: ITEM_KIND_COPY.milestone,
  reminder: ITEM_KIND_COPY.reminder,
};

export const MARKER_KIND_COPY: CopyMap<MarkerKind> = {
  deadline: { label: "Deadline", icon: Hourglass, tone: "deadline" },
  send_by: { label: "Send by", icon: Send, tone: "deadline" },
  cancel_by: { label: "Cancel by", icon: FileX, tone: "warn" },
  renewal: { label: "Renews", icon: Recycle, tone: "contract" },
  expiry: { label: "Expires", icon: CalendarX, tone: "expiry" },
  payment: { label: "Payment", icon: Euro, tone: "payment" },
  appointment: { label: "Appointment", icon: CalendarClock, tone: "appointment" },
  other: { label: "Date", icon: CalendarClock, tone: "neutral" },
};

export const LANE_BAR_KIND_COPY: CopyMap<LaneBarKind> = {
  contract: { label: "Contract term", icon: Signature, tone: "contract" },
  notice_window: { label: "Time to cancel", icon: FileX, tone: "warn" },
  validity: { label: "Valid", icon: IdCard, tone: "expiry" },
  period: { label: "Period", icon: CalendarClock, tone: "milestone" },
  event: { label: "Event", icon: CalendarClock, tone: "appointment" },
};

export const LANE_BAR_STATUS_COPY: CopyMap<LaneBarStatus> = {
  ok: { label: "On track", icon: CircleCheck, tone: "ok" },
  attention: { label: "Coming up", icon: Info, tone: "warn" },
  urgent: { label: "Act now", icon: TriangleAlert, tone: "danger" },
  past: { label: "Past", icon: Clock, tone: "neutral" },
};

// ------------------------------------------------------------------------------------------------
// Ideas
// ------------------------------------------------------------------------------------------------

export const SUGGESTION_KIND_COPY: CopyMap<SuggestionKind> = {
  deadline: { label: "Deadline", icon: Hourglass, tone: "deadline" },
  saving: { label: "Save money", icon: PiggyBank, tone: "ok" },
  risk: { label: "Heads-up", icon: TriangleAlert, tone: "warn" },
  followup: { label: "Follow up", icon: Send, tone: "appointment" },
  hygiene: { label: "Tidy up", icon: Sparkles, tone: "accent" },
  tax: { label: "Tax", icon: Landmark, tone: "expiry" },
  opportunity: { label: "Opportunity", icon: Lightbulb, tone: "milestone" },
  scam: { label: "Possible scam", icon: ShieldAlert, tone: "danger" },
  info: { label: "Good to know", icon: Info, tone: "neutral" },
};

export const SUGGESTION_STATUS_COPY: CopyMap<SuggestionStatus> = {
  new: { label: "New", icon: Sparkles, tone: "accent" },
  accepted: { label: "On it", icon: CircleCheck, tone: "ok" },
  dismissed: { label: "Not relevant", icon: CircleX, tone: "neutral" },
  snoozed: { label: "Snoozed", icon: AlarmClock, tone: "neutral" },
  done: { label: "Done", icon: CircleCheckBig, tone: "ok" },
  expired: { label: "No longer relevant", icon: Clock, tone: "neutral" },
};

// ------------------------------------------------------------------------------------------------
// Contracts
// ------------------------------------------------------------------------------------------------

export const CONTRACT_CATEGORY_COPY: CopyMap<ContractCategory> = {
  mobile: { label: "Mobile phone", icon: Smartphone, tone: "appointment" },
  internet: { label: "Internet", icon: Wifi, tone: "appointment" },
  energy: { label: "Electricity", icon: Zap, tone: "payment" },
  gas: { label: "Gas", icon: Zap, tone: "payment" },
  insurance: { label: "Insurance", icon: Shield, tone: "contract" },
  gym: { label: "Gym", icon: Dumbbell, tone: "ok" },
  streaming: { label: "Streaming", icon: Tv, tone: "milestone" },
  software: { label: "Software", icon: MonitorSmartphone, tone: "milestone" },
  rent: { label: "Rent", icon: House, tone: "contract" },
  employment: { label: "Job", icon: Briefcase, tone: "task" },
  transport: { label: "Transport", icon: TramFront, tone: "appointment" },
  bank: { label: "Bank account", icon: Banknote, tone: "document" },
  membership: { label: "Membership", icon: Handshake, tone: "milestone" },
  other: { label: "Other", icon: FileText, tone: "neutral" },
};

export interface RegimeCopy extends EnumCopy {
  /** the main legal citation for the regime */
  citation: string;
}

export const CONTRACT_REGIME_COPY: Record<ContractRegime, RegimeCopy> = {
  bgb309_new: { label: "Consumer contract (since March 2022)", icon: Scale, tone: "contract", citation: "§ 309 Nr. 9 BGB", hint: "After the minimum term you can cancel any time with at most one month's notice." },
  bgb309_old: { label: "Consumer contract (before March 2022)", icon: Scale, tone: "contract", citation: "§ 309 Nr. 9 BGB (old version)", hint: "Renewals of up to 12 months and up to 3 months' notice were allowed." },
  tkg56: { label: "Phone & internet contract", icon: Smartphone, tone: "contract", citation: "§ 56 TKG", hint: "After the minimum term you can cancel any time with one month's notice." },
  vvg11: { label: "Insurance contract", icon: Shield, tone: "contract", citation: "§ 11 VVG", hint: "Renews every insurance year; cancel before the notice date." },
  sgbv175: { label: "Statutory health insurance", icon: HeartPulse, tone: "contract", citation: "§ 175 SGB V", hint: "12 months' minimum membership; ends at the end of the second following month." },
  stromgvv20: { label: "Basic energy supply", icon: Zap, tone: "contract", citation: "§ 20 StromGVV", hint: "You can cancel any time with two weeks' notice." },
  rent573c: { label: "Tenancy (you as tenant)", icon: House, tone: "contract", citation: "§ 573c BGB", hint: "Notice by the 3rd working day of a month ends the tenancy at the end of the month after next." },
  employment622: { label: "Employment contract", icon: Briefcase, tone: "contract", citation: "§ 622 BGB", hint: "Notice as written in the contract, at least the statutory minimum." },
  as_written: { label: "As written in the contract", icon: ScrollText, tone: "neutral", citation: "Contract terms", hint: "No special rule known — we follow the contract text. Please double-check." },
};

export const CONTRACT_STATUS_COPY: CopyMap<ContractStatus> = {
  active: { label: "Active", icon: CircleCheck, tone: "ok" },
  cancelled: { label: "Cancelled", icon: FileX, tone: "neutral" },
  ended: { label: "Ended", icon: Clock, tone: "neutral" },
};

export const COST_INTERVAL_COPY: CopyMap<CostInterval> = {
  monthly: { label: "per month", icon: Repeat, tone: "neutral" },
  quarterly: { label: "per quarter", icon: Repeat, tone: "neutral" },
  yearly: { label: "per year", icon: Repeat, tone: "neutral" },
  once: { label: "one-off", icon: HandCoins, tone: "neutral" },
};

export const NOTICE_BASIS_COPY: CopyMap<NoticeBasis> = {
  end_of_term: { label: "to the end of the term", icon: CalendarClock, tone: "neutral" },
  any_time: { label: "at any time", icon: CalendarClock, tone: "neutral" },
  end_of_month: { label: "to the end of a month", icon: CalendarClock, tone: "neutral" },
};

// ------------------------------------------------------------------------------------------------
// Letters
// ------------------------------------------------------------------------------------------------

export const DRAFT_KIND_COPY: CopyMap<DraftKind> = {
  cancellation: { label: "Cancellation", icon: FileX, tone: "contract", hint: "End a contract (Kündigung)." },
  objection: { label: "Objection", icon: Scale, tone: "expiry", hint: "Object to an official decision (Einspruch / Widerspruch)." },
  general_reply: { label: "Reply", icon: Mail, tone: "appointment", hint: "Answer a letter, ask a question or send a document." },
};

export const DRAFT_STATUS_COPY: CopyMap<DraftStatus> = {
  draft: { label: "Draft", icon: FilePen, tone: "neutral" },
  final: { label: "Ready to send", icon: FileCheckCorner, tone: "accent" },
  sent: { label: "Sent", icon: Send, tone: "ok" },
};

export const SEND_CHANNEL_COPY: CopyMap<SendChannelKind> = {
  online_button: { label: "Cancel button on their website", icon: MousePointerClick, tone: "accent" },
  email: { label: "Email", icon: Mail, tone: "appointment" },
  fax: { label: "Fax", icon: Printer, tone: "neutral" },
  letter: { label: "Letter by post", icon: Mail, tone: "neutral" },
  registered_letter: { label: "Einschreiben (registered letter)", icon: Stamp, tone: "contract" },
  in_person: { label: "In person", icon: UserRound, tone: "neutral" },
  portal: { label: "Online portal", icon: Globe, tone: "accent" },
};

export const SEND_FORM_COPY: CopyMap<SendForm> = {
  text_form: { label: "Text form — email or letter is fine", icon: Mail, tone: "ok" },
  written_form: { label: "Written form — print, sign by hand and post", icon: Signature, tone: "warn" },
  any: { label: "Any form", icon: Mail, tone: "neutral" },
};

export const REMEDY_TYPE_COPY: CopyMap<RemedyType> = {
  einspruch: { label: "Einspruch (objection)", icon: Scale, tone: "expiry" },
  widerspruch: { label: "Widerspruch (objection)", icon: Scale, tone: "expiry" },
  klage: { label: "Klage (court action) — get advice", icon: Scale, tone: "danger" },
  none: { label: "No objection possible", icon: Info, tone: "neutral" },
  unclear: { label: "Unclear — get advice", icon: TriangleAlert, tone: "warn" },
};

// ------------------------------------------------------------------------------------------------
// People & organisations
// ------------------------------------------------------------------------------------------------

export const PARTY_KIND_COPY: CopyMap<PartyKind> = {
  authority: { label: "Authority", icon: Building, tone: "milestone" },
  tax_office: { label: "Tax office", icon: Landmark, tone: "expiry" },
  immigration_office: { label: "Immigration office", icon: Stamp, tone: "expiry" },
  health_insurer: { label: "Health insurer", icon: HeartPulse, tone: "appointment" },
  insurer: { label: "Insurer", icon: Shield, tone: "contract" },
  bank: { label: "Bank", icon: Banknote, tone: "document" },
  landlord: { label: "Landlord", icon: House, tone: "contract" },
  employer: { label: "Employer", icon: Briefcase, tone: "task" },
  university: { label: "University", icon: GraduationCap, tone: "milestone" },
  utility: { label: "Utility", icon: Zap, tone: "payment" },
  telecom: { label: "Phone & internet", icon: Smartphone, tone: "appointment" },
  retailer: { label: "Shop", icon: Store, tone: "payment" },
  doctor: { label: "Doctor", icon: Stethoscope, tone: "appointment" },
  gym: { label: "Gym", icon: Dumbbell, tone: "ok" },
  public_broadcaster: { label: "Broadcasting fee office", icon: Radio, tone: "payment" },
  transport: { label: "Public transport", icon: TramFront, tone: "appointment" },
  person: { label: "Person", icon: UserRound, tone: "neutral" },
  company: { label: "Company", icon: Building, tone: "neutral" },
  other: { label: "Organisation", icon: Building, tone: "neutral" },
};

// ------------------------------------------------------------------------------------------------
// Pipeline & misc
// ------------------------------------------------------------------------------------------------

export const CONFIDENCE_COPY: CopyMap<Confidence> = {
  high: { label: "High confidence", icon: CircleCheck, tone: "ok" },
  medium: { label: "Medium confidence — worth a second look", icon: Info, tone: "warn" },
  low: { label: "Low confidence — please check", icon: TriangleAlert, tone: "danger" },
};

/** The 5 steps shown in the upload stepper. */
export const PIPELINE_STEPS = [
  { id: "reading", label: "Reading" },
  { id: "understanding", label: "Understanding" },
  { id: "checking", label: "Checking" },
  { id: "computing", label: "Computing dates", short: "Dates" },
  { id: "filing", label: "Filing" },
] as const;
export type PipelineStepId = (typeof PIPELINE_STEPS)[number]["id"];

export const JOB_STAGE_COPY: Record<JobStage, EnumCopy & { step: number }> = {
  intake: { label: "Opening the file", icon: CloudUpload, tone: "accent", step: 0 },
  text: { label: "Reading the text", icon: FileText, tone: "accent", step: 0 },
  transcribe: { label: "Reading the photo", icon: ScanText, tone: "accent", step: 0 },
  extract: { label: "Understanding the letter", icon: BookOpen, tone: "accent", step: 1 },
  verify: { label: "Checking every fact against the page", icon: CircleCheck, tone: "accent", step: 2 },
  compute: { label: "Computing dates with the rules", icon: Scale, tone: "accent", step: 3 },
  link: { label: "Linking to your records", icon: Folder, tone: "accent", step: 4 },
  plan: { label: "Updating your to-dos & dates", icon: ListTodo, tone: "accent", step: 4 },
  done: { label: "Filed", icon: CircleCheckBig, tone: "ok", step: 5 },
};

/** Map a backend stage name to the stepper index (0..4, 5 = finished). Unknown → 0. */
export function stageToStep(stage: string | null | undefined): number {
  if (!stage) return 0;
  return (JOB_STAGE_COPY as Record<string, { step: number }>)[stage]?.step ?? 0;
}

export const LLM_PURPOSE_LABELS: Record<string, string> = {
  transcribe: "Reading photos",
  extract: "Understanding letters",
  review: "Weekly review (Ideas)",
  ask: "Answering questions",
  draft: "Drafting letters",
  brief: "Daily note",
  capture: "Quick capture",
  bank: "Bank statements",
};

// ------------------------------------------------------------------------------------------------
// Lookup helpers
// ------------------------------------------------------------------------------------------------

/** Turn an unknown machine value into readable text ("needs_review" → "Needs review"). Last resort. */
export function humanize(value: string): string {
  const s = value.replace(/[_-]+/g, " ").trim();
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

const FALLBACK: EnumCopy = { label: "Other", icon: FileText, tone: "neutral" };

/** Safe lookup: returns the copy for `value`, or a humanised fallback (never the raw value). */
export function copyFor<C extends EnumCopy = EnumCopy>(map: Readonly<Record<string, C>>, value: string | null | undefined): C | EnumCopy {
  if (value && Object.prototype.hasOwnProperty.call(map, value)) return map[value]!;
  return value ? { ...FALLBACK, label: humanize(value) } : FALLBACK;
}

/** Label only (see {@link copyFor}). */
export function enumLabel(map: Readonly<Record<string, EnumCopy>>, value: string | null | undefined): string {
  return copyFor(map, value).label;
}

export const documentKindLabel = (k: DocumentKind | string | null | undefined) => enumLabel(DOCUMENT_KIND_COPY, k);
export const itemKindLabel = (k: ItemKind | string | null | undefined) => enumLabel(ITEM_KIND_COPY, k);
export const areaLabel = (k: Area | string | null | undefined) => enumLabel(AREA_COPY, k);
export const partyKindLabel = (k: PartyKind | string | null | undefined) => enumLabel(PARTY_KIND_COPY, k);
export const regimeLabel = (k: ContractRegime | string | null | undefined) => enumLabel(CONTRACT_REGIME_COPY, k);

/** All copy maps with the enum arrays they must cover (used by tests). */
export const ENUM_COVERAGE: { name: string; values: readonly string[]; map: Record<string, EnumCopy> }[] = [
  { name: "DocumentKind", values: DOCUMENT_KINDS, map: DOCUMENT_KIND_COPY },
  { name: "DocumentStatus", values: DOCUMENT_STATUSES, map: DOCUMENT_STATUS_COPY },
  { name: "Direction", values: DIRECTIONS, map: DIRECTION_COPY },
  { name: "Grounding", values: GROUNDINGS, map: GROUNDING_COPY },
  { name: "ItemKind", values: ITEM_KINDS, map: ITEM_KIND_COPY },
  { name: "ItemStatus", values: ITEM_STATUSES, map: ITEM_STATUS_COPY },
  { name: "Priority", values: PRIORITIES, map: PRIORITY_COPY },
  { name: "Area", values: AREAS, map: AREA_COPY },
  { name: "AreaStatus", values: AREA_STATUSES, map: AREA_STATUS_COPY },
  { name: "TimelineType", values: TIMELINE_TYPES, map: TIMELINE_TYPE_COPY },
  { name: "MarkerKind", values: MARKER_KINDS, map: MARKER_KIND_COPY },
  { name: "LaneBarKind", values: LANE_BAR_KINDS, map: LANE_BAR_KIND_COPY },
  { name: "LaneBarStatus", values: LANE_BAR_STATUSES, map: LANE_BAR_STATUS_COPY },
  { name: "SuggestionKind", values: SUGGESTION_KINDS, map: SUGGESTION_KIND_COPY },
  { name: "SuggestionStatus", values: SUGGESTION_STATUSES, map: SUGGESTION_STATUS_COPY },
  { name: "ContractCategory", values: CONTRACT_CATEGORIES, map: CONTRACT_CATEGORY_COPY },
  { name: "ContractRegime", values: CONTRACT_REGIMES, map: CONTRACT_REGIME_COPY },
  { name: "ContractStatus", values: CONTRACT_STATUSES, map: CONTRACT_STATUS_COPY },
  { name: "CostInterval", values: COST_INTERVALS, map: COST_INTERVAL_COPY },
  { name: "NoticeBasis", values: NOTICE_BASES, map: NOTICE_BASIS_COPY },
  { name: "DraftKind", values: DRAFT_KINDS, map: DRAFT_KIND_COPY },
  { name: "DraftStatus", values: DRAFT_STATUSES, map: DRAFT_STATUS_COPY },
  { name: "SendChannel", values: SEND_CHANNELS, map: SEND_CHANNEL_COPY },
  { name: "SendForm", values: SEND_FORMS, map: SEND_FORM_COPY },
  { name: "RemedyType", values: REMEDY_TYPES, map: REMEDY_TYPE_COPY },
  { name: "PartyKind", values: PARTY_KINDS, map: PARTY_KIND_COPY },
  { name: "Confidence", values: CONFIDENCES, map: CONFIDENCE_COPY },
  { name: "JobStage", values: JOB_STAGES, map: JOB_STAGE_COPY },
];

// ------------------------------------------------------------------------------------------------
// Raw-enum guard
// ------------------------------------------------------------------------------------------------

/** Every enum value that contains an underscore or digit — these must never appear in UI text. */
const DISTINCTIVE_RAW = new Set<string>(
  ENUM_COVERAGE.flatMap((c) => c.values).filter((v) => /[_\d]/.test(v)),
);
// extra machine values that are not in the arrays above
["due_date_source", "model_read", "slot_key", "user_modified", "de_admin_post", "text_form", "written_form"].forEach(
  (v) => DISTINCTIVE_RAW.add(v),
);

/** Single-word lowercase enum values; flagged only when they are an element's entire text. */
const WORD_RAW = new Set<string>(ENUM_COVERAGE.flatMap((c) => c.values).filter((v) => !/[_\d]/.test(v)));

/** A ledger record id (`doc_0b2t88kqsf2n`, `itm_…`) — never shown as text (see `RefText`). */
export const RECORD_ID_RE = /\b(doc|itm|ctr|pty|cas|drf|sug|thr)_[a-z0-9]{8,}\b/;

/** Record id prefix → the kind of record it names (those a person can open). */
export const RECORD_TYPES: Partial<Record<string, "document" | "item" | "contract" | "party">> = {
  doc: "document",
  itm: "item",
  ctr: "contract",
  pty: "party",
};

export type TextPart = { kind: "text"; text: string } | { kind: "id"; id: string; prefix: string };

/** Split `text` into plain runs and record ids. */
export function splitRecordIds(text: string): TextPart[] {
  const parts: TextPart[] = [];
  const re = new RegExp(RECORD_ID_RE.source, "g");
  let last = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: text.slice(last, at) });
    parts.push({ kind: "id", id: m[0], prefix: m[1]! });
    last = at + m[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

/** Return the raw enum tokens (snake_case / regime codes) and record ids found in `text`. */
export function findRawEnums(text: string): string[] {
  const found = new Set<string>();
  const tokens = text.match(/[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+|[a-z]+\d+[a-z_]*/g) ?? [];
  for (const t of tokens) if (DISTINCTIVE_RAW.has(t) || RECORD_ID_RE.test(t)) found.add(t);
  return [...found];
}

/**
 * Throw if `text` contains raw enum values (e.g. "needs_review", "tax_assessment", "bgb309_new").
 * With `exactWord`, also fails when the whole text is a bare lowercase enum word ("deadline").
 */
export function assertNoRawEnums(text: string, opts: { exactWord?: boolean } = {}): void {
  const found = findRawEnums(text);
  if (opts.exactWord && WORD_RAW.has(text.trim())) found.push(text.trim());
  if (found.length) throw new Error(`Raw enum value(s) shown to the user: ${found.join(", ")}`);
}

/**
 * DOM variant for render tests: checks the element's full text for snake_case enum values and
 * every leaf element whose entire text is a bare lowercase enum word (a badge showing "deadline").
 */
export function assertNoRawEnumsInElement(root: Element): void {
  assertNoRawEnums(root.textContent ?? "");
  const leaves = root.querySelectorAll("*");
  for (const el of Array.from(leaves)) {
    if (el.children.length === 0) {
      const t = (el.textContent ?? "").trim();
      if (t && WORD_RAW.has(t)) throw new Error(`Raw enum value shown to the user: "${t}" in <${el.tagName.toLowerCase()}>`);
    }
  }
}
