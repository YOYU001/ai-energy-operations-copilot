import AppShell from "@/components/layout/AppShell";
import Sidebar from "@/components/layout/Sidebar";
import TopNav from "@/components/layout/TopNav";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AppShell sidebar={<Sidebar />} topNav={<TopNav />}>
      {children}
    </AppShell>
  );
}
