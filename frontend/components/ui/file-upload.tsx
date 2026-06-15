"use client";

import { useRef, DragEvent, ChangeEvent, useState } from "react";
import { motion } from "framer-motion";
import clsx from "clsx";
import {
  UploadCloud,
  File as FileIcon,
  Trash2,
  Loader,
  CheckCircle,
} from "lucide-react";

interface FileUploadProps {
  file: File | null;
  onFileSelect: (file: File) => void;
  onRemove: () => void;
  isUploading?: boolean;
  progress?: number;
  error?: string | null;
  analyzeStepLabel?: string;
}

export default function FileUpload({
  file,
  onFileSelect,
  onRemove,
  isUploading = false,
  progress = 0,
  error,
  analyzeStepLabel,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFileSelect(dropped);
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const onDragLeave = () => setIsDragging(false);

  const onSelect = (e: ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) onFileSelect(selected);
  };

  const formatFileSize = (bytes: number): string => {
    if (!bytes) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  };

  return (
    <div className="w-full mx-auto">
      {/* Drop zone */}
      {!file ? (
        <motion.div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          initial={false}
          animate={{
            borderColor: isDragging ? "var(--color-accent)" : "rgba(0,0,0,0.1)",
            scale: isDragging ? 1.02 : 1,
          }}
          whileHover={{ scale: 1.01 }}
          transition={{ duration: 0.2 }}
          className={clsx(
            "relative rounded-2xl p-8 md:p-12 text-center cursor-pointer bg-subtle/50 border border-dashed border-border shadow-sm hover:shadow-md backdrop-blur group",
            isDragging && "ring-4 ring-accent/10 border-accent",
          )}
        >
          <div className="flex flex-col items-center gap-5">
            <motion.div
              animate={{ y: isDragging ? [-5, 0, -5] : 0 }}
              transition={{
                duration: 1.5,
                repeat: isDragging ? Infinity : 0,
                ease: "easeInOut",
              }}
              className="relative"
            >
              <UploadCloud
                className={clsx(
                  "w-12 h-12 md:w-16 md:h-16 drop-shadow-sm",
                  isDragging
                    ? "text-accent"
                    : "text-muted group-hover:text-accent transition-colors duration-300",
                )}
              />
            </motion.div>

            <div className="space-y-2">
              <h3 className="text-lg md:text-xl font-semibold text-foreground">
                {isDragging ? "Drop your resume here" : "Upload your resume"}
              </h3>
              <p className="text-muted text-sm md:text-base max-w-md mx-auto">
                {isDragging ? (
                  <span className="font-medium text-accent">Release to upload</span>
                ) : (
                  <>
                    Drag & drop file here, or{" "}
                    <span className="text-accent font-medium">browse</span>
                  </>
                )}
              </p>
              <p className="text-xs text-muted/80">
                PDF or DOCX · up to 10MB
              </p>
            </div>

            <input
              ref={inputRef}
              type="file"
              hidden
              onChange={onSelect}
              accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            />
          </div>
        </motion.div>
      ) : (
        /* File status view */
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          className="px-4 py-4 flex items-start gap-4 rounded-xl bg-card border border-border shadow-sm"
        >
          {/* Icon */}
          <div className="relative flex-shrink-0">
            <div className="w-12 h-12 rounded bg-subtle flex items-center justify-center">
              <FileIcon className="w-6 h-6 text-accent" />
            </div>
            {progress === 100 && !isUploading && (
              <motion.div
                initial={{ opacity: 0, scale: 0.5 }}
                animate={{ opacity: 1, scale: 1 }}
                className="absolute -right-2 -bottom-2 bg-white rounded-full shadow-sm"
              >
                <CheckCircle className="w-5 h-5 text-success" />
              </motion.div>
            )}
          </div>

          {/* Info & Progress */}
          <div className="flex-1 min-w-0">
            <div className="flex flex-col gap-1 w-full">
              <div className="flex items-center justify-between gap-2">
                <h4 className="font-medium text-sm md:text-base truncate text-foreground" title={file.name}>
                  {file.name}
                </h4>
                {!isUploading && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemove();
                    }}
                    className="p-1 hover:bg-subtle rounded-full text-muted hover:text-danger transition-colors"
                    aria-label="Remove file"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>

              <div className="flex items-center justify-between text-xs text-muted">
                <span>{isUploading ? (analyzeStepLabel || "Uploading...") : formatFileSize(file.size)}</span>
                {isUploading && (
                  <span className="flex items-center gap-1.5 font-medium text-accent">
                    {Math.round(progress)}%
                    <Loader className="w-3 h-3 animate-spin" />
                  </span>
                )}
              </div>
            </div>

            {/* Progress bar */}
            {(isUploading || progress > 0) && (
              <div className="w-full h-1.5 bg-subtle rounded-full overflow-hidden mt-2">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.4, ease: "easeOut" }}
                  className={clsx(
                    "h-full rounded-full",
                    progress < 100 ? "bg-accent" : "bg-success"
                  )}
                />
              </div>
            )}
          </div>
        </motion.div>
      )}

      {error && (
        <motion.p
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="text-xs text-danger mt-3 px-1"
        >
          {error}
        </motion.p>
      )}
    </div>
  );
}
