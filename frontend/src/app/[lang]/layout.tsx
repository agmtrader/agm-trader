import "../globals.css"
import { NextAuthProvider } from "../../utils/providers/NextAuthProvider"
import { TranslationProvider } from "../../utils/providers/TranslationProvider"

export default async function Layout(
  props: Readonly<{
    children: React.ReactNode
    params:Promise<{lang:string}>
  }>
) {
  const params = await props.params;

  const {
    lang
  } = params;

  const {
    children
  } = props;

  return (
    <NextAuthProvider>
      <TranslationProvider lang={lang}>
        {children}
      </TranslationProvider>
    </NextAuthProvider>
  )
}