/**
 * Design-system gallery (`/dev/ui`): every component with realistic data. A living reference for
 * page builders and a visual regression check in light / dark / mobile.
 */
import { useState, type ReactNode } from "react";
import {
  CalendarPlus,
  Download,
  Ellipsis,
  FileText,
  PenLine,
  Plus,
  RotateCw,
  Trash2,
  Euro,
  CircleCheck,
} from "lucide-react";
import { Page, PageHeader } from "@/components/shell/Page";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  Checkbox,
  ConfidenceNote,
  Countdown,
  CountBadge,
  DateLeaf,
  DateText,
  Dialog,
  Disclaimer,
  ADVICE_LINKS,
  Drawer,
  EmptyState,
  Field,
  Glossary,
  GroundingBadge,
  IconButton,
  Input,
  Kbd,
  KindBadge,
  LoadError,
  KindIcon,
  Menu,
  Money,
  PartyChip,
  ProgressRing,
  SectionHeader,
  SegmentedControl,
  Select,
  Skeleton,
  SkeletonCard,
  StatusPill,
  Stepper,
  Switch,
  TabPanel,
  Tabs,
  Textarea,
  Tooltip,
  useToast,
} from "@/components/ui";
import { ITEM_KINDS, SUGGESTION_KINDS, type ComputationReceipt, type DateSpec } from "@/api/types";
import { WhyThisDate } from "@/features/document/WhyThisDate";
import { useDashboard } from "@/api/hooks";
import { PIPELINE_STEPS } from "@/lib/copy";
import { useToday } from "@/lib/today";
import { addDays, format } from "date-fns";

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** "Why this date?" samples: fixtures here, so the gallery shows them with any data (not only the demo's). */
const SPEC_BASE: DateSpec = {
  type: "relative",
  date: null,
  time: null,
  anchor: null,
  anchor_date: null,
  amount: null,
  unit: null,
  delivery_rule: "none",
  shift_rule: "auto",
  nature: "other",
  legal_basis: null,
  text: "",
};
const RECEIPT_BASE: Omit<ComputationReceipt, "due_date" | "summary"> = {
  send_by: null,
  safe_date: null,
  holiday_calendar: "Germany + North Rhine-Westphalia (NW)",
  steps: [],
  rule_ids: [],
  warnings: [],
  confidence: "high",
};
const PHONE_SAMPLE = {
  spec: {
    ...SPEC_BASE,
    anchor: "explicit_date",
    anchor_date: "2026-11-14",
    amount: 1,
    unit: "months",
    nature: "notice",
    text: "Kündigungsfrist: 1 Monat zum Ende der Mindestvertragslaufzeit, danach jederzeit mit einer Frist von einem Monat.",
  } satisfies DateSpec,
  receipt: {
    ...RECEIPT_BASE,
    due_date: "2026-10-14",
    send_by: "2026-10-08",
    summary:
      "The minimum term of 24 months from 15 Nov 2024 ends on Sat 14 Nov 2026. With one month's notice, FunkNetz must receive your cancellation by Wed 14 Oct. Post it by Thu 8 Oct — or use their cancel button until the 14th.",
    steps: [
      { label: "Contract started", date: "2024-11-15", rule_id: null, citation: null },
      { label: "Minimum term of 24 months ends", date: "2026-11-14", rule_id: "bgb188_months", citation: "§ 188 Abs. 2 BGB" },
      { label: "One month's notice → must arrive by", date: "2026-10-14", rule_id: "tkg56", citation: "§ 56 Abs. 3 TKG" },
      { label: "Allow 4 working days for the post", date: "2026-10-08", rule_id: "postal_buffer", citation: null },
    ],
    rule_ids: ["tkg56", "bgb188_months", "postal_buffer"],
  } satisfies ComputationReceipt,
};
const PARKING_SAMPLE = {
  spec: { ...SPEC_BASE, anchor: "receipt", amount: 1, unit: "weeks", nature: "payment", text: "Bitte zahlen Sie das Verwarnungsgeld innerhalb einer Woche." } satisfies DateSpec,
  receipt: {
    ...RECEIPT_BASE,
    due_date: "2026-09-29",
    summary: "One week after the letter arrived. We don't know when it arrived, so we count from the letter date (22 Sep) — the earliest possible.",
    steps: [
      { label: "Letter dated", date: "2026-09-22", rule_id: null, citation: null },
      { label: "Arrival date unknown — using the letter date instead (earliest possible)", date: "2026-09-22", rule_id: "receipt_fallback", citation: null },
      { label: "One week later", date: "2026-09-29", rule_id: "bgb188_weeks", citation: "§ 188 Abs. 2 BGB" },
    ],
    rule_ids: ["receipt_fallback", "bgb188_weeks"],
    confidence: "medium",
  } satisfies ComputationReceipt,
};

function Block({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <section className="mb-12">
      <SectionHeader title={title} description={note} />
      <Card padding="lg">{children}</Card>
    </section>
  );
}

function Row({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:gap-6">
      {label ? <div className="w-40 shrink-0 text-[13px] font-medium text-muted">{label}</div> : null}
      <div className="flex min-w-0 flex-wrap items-center gap-2.5">{children}</div>
    </div>
  );
}

export default function UiGallery() {
  const today = useToday();
  const { toast } = useToast();
  const { data: dash } = useDashboard();
  const [dialog, setDialog] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [tab, setTab] = useState("all");
  const [seg, setSeg] = useState<"list" | "lanes">("lanes");
  const [range, setRange] = useState<"all" | "open">("all");
  const [sw, setSw] = useState(true);
  const [step, setStep] = useState(2);
  const d = (n: number) => format(addDays(today, n), "yyyy-MM-dd");

  return (
    <Page title="Design system">
      <PageHeader
        eyebrow="Ordnung · calm paper"
        title="Design system"
        description="Every component, with Sam Rivera's sample data. Use these building blocks — they handle copy, colour, contrast and accessibility for you."
      />

      <Block title="Buttons">
        <Row label="Variants">
          <Button variant="primary" icon={Plus}>Add letters</Button>
          <Button icon={PenLine}>Draft letter</Button>
          <Button variant="soft" icon={CalendarPlus}>Add to calendar</Button>
          <Button variant="ghost">Not relevant</Button>
          <Button variant="danger" icon={Trash2}>Delete</Button>
          <Button variant="link">Why this date?</Button>
        </Row>
        <Row label="Sizes & states">
          <Button size="sm">Small</Button>
          <Button>Medium</Button>
          <Button size="lg" variant="primary">Large</Button>
          <Button loading>Saving</Button>
          <Button disabled>Disabled</Button>
        </Row>
        <Row label="Icon buttons">
          <IconButton icon={Ellipsis} label="More actions" />
          <IconButton icon={RotateCw} label="Reprocess" variant="secondary" />
          <IconButton icon={Download} label="Download" variant="primary" />
          <Menu
            items={[
              { label: "Draft reply", icon: PenLine, onSelect: () => toast({ title: "Draft reply" }) },
              { label: "Add to calendar", icon: CalendarPlus, onSelect: () => toast({ title: "Added" }) },
              { label: "Reprocess", icon: RotateCw, onSelect: () => toast({ title: "Reprocessing" }) },
              "separator",
              { label: "Delete letter", icon: Trash2, danger: true, onSelect: () => toast.error("Deleted") },
            ]}
          >
            <IconButton icon={Ellipsis} label="Open menu" variant="secondary" />
          </Menu>
        </Row>
      </Block>

      <Block title="Kinds & status" note="Never show raw enum values — these components map them to calm, human copy.">
        <Row label="To-dos & dates">
          {ITEM_KINDS.map((k) => (
            <KindBadge key={k} kind={k} />
          ))}
        </Row>
        <Row label="Letters">
          {(["tax_assessment", "dunning", "rent_lease", "price_increase", "residence_permit", "fine", "broadcasting_fee"] as const).map((k) => (
            <KindBadge key={k} docKind={k} />
          ))}
        </Row>
        <Row label="Ideas">
          {SUGGESTION_KINDS.map((k) => (
            <KindBadge key={k} ideaKind={k} />
          ))}
        </Row>
        <Row label="Money">
          <KindBadge kind="payment" />
          <KindBadge kind="payment" direction="in" />
        </Row>
        <Row label="Date leaves">
          <DateLeaf date={d(1)} size="sm" />
          <DateLeaf date={d(0)} size="sm" tone="today" />
          <DateLeaf date={d(-3)} size="sm" tone="muted" />
          <DateLeaf date={d(10)} size="md" />
          <DateLeaf date={d(-1)} size="md" tone="danger" />
          <DateLeaf date={d(10)} size="lg" tone="warn" />
        </Row>
        <Row label="Icons">
          {ITEM_KINDS.map((k) => (
            <KindIcon key={k} kind={k} />
          ))}
          <KindIcon docKind="tax_assessment" size="lg" />
          <KindIcon category="mobile" size="lg" />
          <KindIcon area="residence" size="lg" />
        </Row>
        <Row label="Status">
          <StatusPill of="document" status="needs_review" />
          <StatusPill of="document" status="processing" />
          <StatusPill of="document" status="processed" />
          <StatusPill of="document" status="failed" />
          <StatusPill of="item" status="done" marker="icon" />
          <StatusPill of="draft" status="sent" />
          <StatusPill of="area" status="attention" />
        </Row>
        <Row label="Badges">
          <Badge tone="accent" dot>New</Badge>
          <Badge tone="warn">Please check</Badge>
          <Badge tone="danger" variant="solid">Possible scam</Badge>
          <Badge tone="ok" icon={CircleCheck} variant="outline">Paid</Badge>
          <CountBadge count={3} tone="warn" />
        </Row>
      </Block>

      <Block title="Evidence & trust" note="SPEC §21 wording: never “verified”.">
        <Row label="Grounding">
          <GroundingBadge grounding="verified" page={2} />
          <GroundingBadge grounding="model_read" page={1} />
          <GroundingBadge grounding="unverified" />
          <GroundingBadge grounding="user" />
          <GroundingBadge grounding="verified" page={1} compact />
        </Row>
        <Row label="Confidence">
          <div className="grid w-full gap-3 sm:grid-cols-2">
            <ConfidenceNote confidence="medium" warnings={["The letter date was read from a photo. Please compare it with the letter."]} />
            <ConfidenceNote confidence="low" warnings={["We don't know when this letter arrived."]} />
          </div>
        </Row>
        <Row label="Why this date?">
          <WhyThisDate receipt={PHONE_SAMPLE.receipt} spec={PHONE_SAMPLE.spec} area="home" context="phone contract" />
          <WhyThisDate receipt={PARKING_SAMPLE.receipt} spec={PARKING_SAMPLE.spec} area="mobility" context="parking fine" />
        </Row>
        <Row label="Glossary">
          <p className="text-base text-ink">
            You can file an <Glossary term="Einspruch" /> within a month of the <Glossary term="Bekanntgabe" />. Check the{" "}
            <Glossary term="Rechtsbehelfsbelehrung" /> and quote your <Glossary term="Aktenzeichen" />.
          </p>
        </Row>
        <Row label="Disclaimer">
          <Disclaimer advice={ADVICE_LINKS.rent} />
        </Row>
      </Block>

      <Block title="Dates & money" note="Relative days use the app's today (demo: Mon 28 Sep 2026), never the browser clock.">
        <Row label="Countdown">
          <Countdown date={d(-2)} />
          <Countdown date={d(0)} />
          <Countdown date={d(1)} />
          <Countdown date={d(5)} />
          <Countdown date={d(10)} />
          <Countdown date={d(45)} />
        </Row>
        <Row label="Pills">
          <Countdown date={d(-2)} variant="pill" />
          <Countdown date={d(2)} variant="pill" />
          <Countdown date={d(6)} variant="pill" />
          <Countdown date={d(20)} variant="pill" />
        </Row>
        <Row label="With prefix">
          <Countdown date="2026-10-08" prefix="send by" />
          <Countdown date="2026-10-14" showDate time="10:30" />
        </Row>
        <Row label="Dates">
          <DateText date="2026-10-16" />
          <DateText date="2027-02-10" />
          <DateText date="2026-10-16" style="long" />
          <DateText date="2026-10-16" style="numeric" />
          <DateText date={null} />
        </Row>
        <Row label="Money">
          <Money amount={184.3} />
          <Money amount={34.99} interval="monthly" />
          <Money amount={84} signed interval="yearly" tone="danger" />
          <Money amount={324} tone="in" />
          <Money amount={1440} decimals="auto" />
        </Row>
        <Row label="People & organisations">
          <PartyChip id="pty_wohnbau" name="Wohnbau Musterstadt eG" kind="landlord" />
          <PartyChip id="pty_abh" name="Ausländerbehörde Musterstadt" kind="immigration_office" showKind />
          <PartyChip name="Unknown sender" />
        </Row>
      </Block>

      <Block title="Progress">
        <Row label="Stepper">
          <div className="w-full max-w-md space-y-6">
            <Stepper steps={PIPELINE_STEPS} current={step} labels="all" live />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => setStep((s) => Math.max(0, s - 1))}>Back</Button>
              <Button size="sm" onClick={() => setStep((s) => Math.min(PIPELINE_STEPS.length, s + 1))}>Next stage</Button>
            </div>
            <Stepper steps={PIPELINE_STEPS} current={3} status="error" size="sm" labels="current" />
          </div>
        </Row>
        <Row label="Ring">
          <ProgressRing value={dash?.stats.verified_ratio ?? 0.86} label="Facts found in the letter" />
          <ProgressRing value={0.4} tone="warn" size={56} stroke={5} label="Progress" />
          <ProgressRing value={1} tone="ok" label="Done">
            <CircleCheck className="size-4 text-ok" />
          </ProgressRing>
        </Row>
      </Block>

      <Block title="Navigation & inputs">
        <Row label="Tabs">
          <div className="w-full">
            <Tabs
              id="gallery-tabs"
              label="Filter letters"
              value={tab}
              onChange={setTab}
              items={[
                { value: "all", label: "All", count: dash?.stats.documents ?? 21 },
                { value: "check", label: "Please check", count: 1 },
                { value: "private", label: "Private", count: 0 },
              ]}
            />
            <TabPanel id="gallery-tabs" value="all" current={tab} className="pt-3 text-base text-muted">All letters…</TabPanel>
            <TabPanel id="gallery-tabs" value="check" current={tab} className="pt-3 text-base text-muted">Letters that need you…</TabPanel>
            <TabPanel id="gallery-tabs" value="private" current={tab} className="pt-3 text-base text-muted">Kept private — no AI.</TabPanel>
          </div>
        </Row>
        <Row label="Pill tabs">
          <div className="w-full">
            <Tabs
              id="gallery-pill-tabs"
              variant="pill"
              label="Show letters"
              value={range}
              onChange={setRange}
              items={[
                { value: "all", label: "All", count: dash?.stats.documents ?? 21 },
                { value: "open", label: "With open to-dos", count: 6 },
              ]}
            />
            <TabPanel id="gallery-pill-tabs" value="all" current={range} className="pt-3 text-base text-muted">Pill tabs filter what a list shows.</TabPanel>
            <TabPanel id="gallery-pill-tabs" value="open" current={range} className="pt-3 text-base text-muted">Only letters that still need you.</TabPanel>
          </div>
        </Row>
        <Row label="Segmented control">
          <SegmentedControl label="View" value={seg} onChange={setSeg} options={[{ value: "lanes", label: "Life lanes" }, { value: "list", label: "List" }]} />
          <span className="text-sm text-muted">The same track and thumb, for a setting or a view.</span>
        </Row>
        <Row label="Fields">
          <div className="grid w-full gap-4 sm:grid-cols-2">
            <Field label="Your name" hint="Used as the sender on letters.">
              <Input defaultValue="Sam Rivera" />
            </Field>
            <Field label="Region" hint="Decides which public holidays count.">
              <Select defaultValue="NW">
                <option value="NW">North Rhine-Westphalia</option>
                <option value="BY">Bavaria</option>
                <option value="BE">Berlin</option>
              </Select>
            </Field>
            <Field label="Instructions" optional>
              <Textarea placeholder="e.g. ask them to confirm by email" />
            </Field>
            <Field label="Arrival date" error="Please enter a date after the letter date (22 Sep).">
              <Input type="date" defaultValue="2026-09-20" />
            </Field>
            <Switch checked={sw} onCheckedChange={setSw} label="Keep private — no AI" description="Store and search on this computer only." />
            <Checkbox label="Remind me 7 days before" defaultChecked />
          </div>
        </Row>
        <Row label="Keys & tips">
          <span className="inline-flex items-center gap-1 text-base text-muted">
            Search <Kbd>/</Kbd> or <Kbd>{IS_MAC ? "⌘" : "Ctrl"}</Kbd>
            <Kbd>K</Kbd>
          </span>
          <Tooltip content="Found on page 2 of the letter">
            <Button size="sm">Hover or focus me</Button>
          </Tooltip>
        </Row>
      </Block>

      <Block title="Messages">
        <div className="space-y-3">
          <Callout tone="danger" title="This looks like a scam" icon={undefined}>
            The IBAN (LT71 7300 …) differs from the one Beitragsservice Musterstadt used before. Do not pay. No warning does not mean it is safe.
          </Callout>
          <Callout tone="warn" title="Please check: when did this letter arrive?" action={<Button size="sm" variant="primary">Set arrival date</Button>}>
            Until you tell us, we count from the letter date — the earliest possible.
          </Callout>
          <Callout tone="info" title="Read by AI from the photo">There was no text layer, so Claude transcribed the image. Worth a glance.</Callout>
          <Callout tone="success" title="All clear until Friday">Nothing needs you this week.</Callout>
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button onClick={() => toast({ title: "Marked as done", description: "Pay TechMarkt reminder", tone: "success", undo: () => void toast({ title: "Restored" }) })}>
            Toast with undo
          </Button>
          <Button onClick={() => toast.error("That didn't work", { description: "Ordnung isn't reachable." })}>Error toast</Button>
          <Button onClick={() => toast({ title: "3 dates added to your calendar", action: { label: "Open", onClick: () => {} } })}>Toast with action</Button>
        </div>
      </Block>

      <Block title="Overlays">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setDialog(true)}>Open dialog</Button>
          <Button onClick={() => setDrawer(true)}>Open drawer</Button>
          <PartyChip id="pty_funknetz" name="FunkNetz Mobil GmbH" kind="telecom" size="md" />
        </div>
        <Dialog
          open={dialog}
          onClose={() => setDialog(false)}
          title="Mark as paid?"
          description="We'll move “Pay TechMarkt reminder” to done. You can undo this."
          footer={
            <>
              <Button onClick={() => setDialog(false)}>Cancel</Button>
              <Button variant="primary" icon={Euro} onClick={() => setDialog(false)}>
                Mark as paid
              </Button>
            </>
          }
        />
        <Drawer open={drawer} onClose={() => setDrawer(false)} eyebrow="Example" title="Right-side sheet" description="Used for People & organisations.">
          <p className="text-base text-muted">Drawer content.</p>
        </Drawer>
      </Block>

      <Block title="Empty & loading">
        <div className="grid gap-4 md:grid-cols-2 [&>*]:min-w-0">
          <EmptyState
            illustration="clear"
            headingLevel={3}
            title="All clear until Friday"
            description="Nothing needs you this week. Enjoy it."
            action={<Button icon={FileText}>See the timeline</Button>}
          />
          <EmptyState illustration="inbox" headingLevel={3} title="No letters yet" description="Drop a PDF or a phone photo anywhere to start." size="sm" />
          <EmptyState illustration="letter" headingLevel={3} title="No letters written yet" description="Cancel a contract or object to a decision." size="sm" />
          <EmptyState illustration="contract" headingLevel={3} title="No contracts yet" description="Add a contract and Ordnung works out the notice." size="sm" />
          <LoadError what="your letters" headingLevel={3} error={new Error("Failed to fetch")} onRetry={() => toast({ title: "Trying again…" })} className="md:col-span-2" />
          <SkeletonCard />
          <div className="space-y-3">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-24 w-full rounded-xl" />
          </div>
        </div>
      </Block>

      <Block title="Cards">
        <div className="grid gap-4 md:grid-cols-2 [&>*]:min-w-0">
          <Card accent="danger">
            <CardHeader
              title="Pay TechMarkt reminder"
              description={
                <>
                  Invoice <span className="whitespace-nowrap">RE-2026-084213</span> + <Money amount={5} decimals="auto" /> fee
                </>
              }
              action={<Countdown date="2026-09-30" variant="pill" />}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Money amount={94.99} className="text-lg" />
              <Button size="sm" variant="primary" icon={Euro}>Pay</Button>
            </div>
          </Card>
          <Card>
            <CardHeader
              title="Decide on your phone contract"
              description={
                <>
                  FunkNetz Allnet L · <Money amount={34.99} interval="monthly" />
                </>
              }
              icon={PenLine}
            />
            <Countdown date="2026-10-08" prefix="send by" />
          </Card>
        </div>
      </Block>
    </Page>
  );
}
