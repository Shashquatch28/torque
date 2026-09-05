const SkelLine = ({ w }) => <div className={"skel skel-line " + (w || "")} />;
const SkelBlock = () => <div className="skel skel-block" />;

function Panel({ lines }) {
  return (
    <div className="panel">
      {Array.from({ length: lines || 3 }).map((_, i) => (
        <SkelLine key={i} w="w60" />
      ))}
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <>
      <div className="panel hero">
        <div className="skel skel-hero" />
      </div>
      <div className="loop mt">
        {[0, 1, 2].map((i) => (
          <div className="loop-stage" key={i}>
            <SkelLine w="w40" />
            <SkelLine w="w60" />
          </div>
        ))}
      </div>
      <div className="grid cols-2 mt">
        <Panel lines={5} />
        <Panel lines={5} />
      </div>
      <Panel lines={4} />
    </>
  );
}

export function CasesSkeleton() {
  return (
    <div className="panel">
      <SkelLine w="w40" />
      {[0, 1, 2, 3, 4].map((i) => (
        <div className="skel skel-row" key={i} />
      ))}
    </div>
  );
}

export function CaseViewSkeleton() {
  return (
    <>
      <div className="skel skel-line w40" style={{ marginBottom: 12 }} />
      <div className="panel casehead lg">
        <SkelLine w="w60" />
        <SkelLine w="w40" />
        <SkelBlock />
      </div>
      <div className="grid cols-2 mt">
        <Panel lines={4} />
        <Panel lines={4} />
      </div>
      <Panel lines={6} />
    </>
  );
}

export function ConsoleSkeleton() {
  return (
    <div className="panel">
      <SkelLine w="w40" />
      {[0, 1, 2].map((i) => (
        <div className="skel skel-row" key={i} />
      ))}
    </div>
  );
}

export function DemoSkeleton() {
  return (
    <div className="grid cols-2">
      <Panel lines={4} />
      <Panel lines={6} />
    </div>
  );
}

export function AiLoading() {
  return (
    <div className="ai-loading">
      <SkelLine w="w80" />
      <SkelLine w="w60" />
      <SkelLine w="w40" />
    </div>
  );
}
