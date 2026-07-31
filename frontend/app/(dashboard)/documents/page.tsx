import PageShell from "@/components/layout/PageShell";
import { getDocuments } from "@/lib/api/client";

import DocumentsList from "./DocumentsList";
import UploadDocumentForm from "./UploadDocumentForm";

export const dynamic = "force-dynamic";

export default async function DocumentsPage() {
  const documents = await getDocuments();

  return (
    <PageShell title="Documents" description="內部文件知識庫（RAG）">
      <UploadDocumentForm />
      <div className="mt-6">
        <DocumentsList documents={documents} />
      </div>
    </PageShell>
  );
}
