import { CookieCard } from "@/components/CookieCard";

export const CookieBanner = () => {
  return (
    <div
      role="region"
      aria-label="Bandeau de consentement aux cookies"
      className="items-end box-border caret-transparent flex text-[15.3846px] justify-start tracking-[-0.107692px] leading-[21.5385px] outline-[3px] pointer-events-none fixed no-underline w-full z-[101] p-[15.3846px] bottom-0 inset-x-0 md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:p-[14.2222px]"
    >
      <div className="items-center box-border caret-transparent flex text-[15.3846px] justify-center tracking-[-0.107692px] leading-[21.5385px] outline-[3px] fixed no-underline z-[150] p-[9.61538px] inset-[0%] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:p-[8.88889px]"></div>
      <CookieCard />
    </div>
  );
};
