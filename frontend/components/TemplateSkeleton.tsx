"use client";

type Variant = "thumbnail" | "preview";

export function TemplateSkeleton({ variant = "thumbnail" }: { variant?: Variant }) {
  if (variant === "preview") {
    return (
      <div className="w-[80%] max-w-[480px] aspect-[8.5/11] bg-card rounded shadow-md border border-border/60 p-8 space-y-6 animate-pulse select-none">
        <div className="space-y-2 text-center">
          <div className="h-4.5 bg-muted/60 rounded w-1/3 mx-auto" />
          <div className="h-3 bg-muted/50 rounded w-1/2 mx-auto" />
        </div>
        <div className="h-2.5 bg-muted/40 rounded w-3/4 mx-auto" />
        <hr className="border-border/60" />
        <div className="space-y-2">
          <div className="h-3 bg-muted/60 rounded w-1/4" />
          <div className="space-y-1.5">
            <div className="h-2 bg-muted/30 rounded w-full" />
            <div className="h-2 bg-muted/30 rounded w-5/6" />
          </div>
        </div>
        <div className="space-y-3">
          <div className="h-3 bg-muted/60 rounded w-1/4" />
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="h-2.5 bg-muted/50 rounded w-1/3" />
              <div className="h-2 bg-muted/40 rounded w-1/6" />
            </div>
            <div className="space-y-1.5 pl-3">
              <div className="h-2 bg-muted/30 rounded w-11/12" />
              <div className="h-2 bg-muted/30 rounded w-full" />
            </div>
          </div>
        </div>
        <div className="space-y-2.5">
          <div className="h-3 bg-muted/60 rounded w-1/4" />
          <div className="flex gap-2">
            <div className="h-5 bg-muted/40 rounded w-16" />
            <div className="h-5 bg-muted/40 rounded w-20" />
            <div className="h-5 bg-muted/40 rounded w-12" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full p-6 space-y-4 animate-pulse bg-card select-none">
      <div className="space-y-1.5">
        <div className="h-3 bg-muted/60 rounded w-1/3 mx-auto" />
        <div className="h-2 bg-muted/50 rounded w-1/2 mx-auto" />
      </div>
      <div className="h-2 bg-muted/40 rounded w-3/4 mx-auto" />
      <hr className="border-border/40" />
      <div className="space-y-1.5">
        <div className="h-2 bg-muted/60 rounded w-1/4" />
        <div className="h-1.5 bg-muted/30 rounded w-full" />
        <div className="h-1.5 bg-muted/30 rounded w-5/6" />
      </div>
      <div className="space-y-2 pt-2">
        <div className="h-2 bg-muted/60 rounded w-1/4" />
        <div className="h-1.5 bg-muted/30 rounded w-11/12" />
        <div className="h-1.5 bg-muted/30 rounded w-full" />
      </div>
    </div>
  );
}
