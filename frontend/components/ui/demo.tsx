import FileUpload from "@/components/ui/file-upload";
import { useState } from "react";

const Demo = () => {
  const [file, setFile] = useState<File | null>(null);

  return (
    <main className="min-h-screen flex items-center justify-center p-4 bg-background">
      <div className="w-full max-w-xl">
        <FileUpload 
          file={file} 
          onFileSelect={setFile} 
          onRemove={() => setFile(null)} 
        />
      </div>
    </main>
  );
}

export { Demo };
