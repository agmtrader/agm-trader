"use client";
import { useState } from 'react';
import { signIn } from 'next-auth/react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Loader2 } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { formatURL } from '@/utils/language/lang';
import { useTranslationProvider } from '@/utils/providers/TranslationProvider';
import { useToast } from '@/hooks/use-toast';
import Link from 'next/link';
import { Card, CardContent, CardTitle, CardHeader } from '@/components/ui/card';
import Image from 'next/image';
import { motion } from 'framer-motion';
import { containerVariants, itemVariants } from '@/lib/anims';
import { useSession } from 'next-auth/react';
import { error } from 'console';
import LoaderButton from '@/components/misc/LoaderButton';

function SignIn() {

  const { lang, t } = useTranslationProvider()

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get('callbackUrl');

  const {toast} = useToast()

  const { data: session } = useSession()
  if (session) {
    router.push(callbackUrl ? formatURL(callbackUrl, lang) : formatURL('/', lang));
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

  const result = await signIn('credentials', {
        email,
        password,
        redirect: false,
        callbackUrl: callbackUrl ? formatURL(callbackUrl, lang) : formatURL('/', lang),
    });

    if (result?.error) {
      toast({
        title: 'Error',
        description: result.error,
        variant: 'destructive'
      })
    }

    if (result?.status === 200) {
      router.push(callbackUrl ? formatURL(callbackUrl, lang) : formatURL('/', lang));
    }

    setIsLoading(false);
  }

  return (
    <motion.div 
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className='flex items-center h-full justify-center'
    >
      <Card className='w-full max-w-xl p-8'>
        <motion.div variants={itemVariants}>
          <CardHeader className='flex flex-col justify-center items-center gap-2'>
            <Image src='/assets/brand/agm-logo.png' alt='AGM Logo' width={200} height={200} />
            <CardTitle className='text-center font-bold text-3xl'>{t('signin.title')}</CardTitle>
            {callbackUrl === formatURL(`/apply`, lang) && (
              <div className='flex flex-col gap-2 bg-error/20 p-2 rounded-md items-center justify-center'>
                <p className='text-sm text-subtitle text-center'>{t('signin.apply.message')}</p>
              </div>
            )}
            <p className='text-subtitle text-lg text-center'>
              {t('signin.register.message')} <Link href={formatURL('/create-account', lang)} className='underline text-primary font-bold'>{t('signin.register.link')}</Link>
            </p>
          </CardHeader>
        </motion.div>
        <motion.div variants={itemVariants} className='w-full'>
          <CardContent className='w-full flex flex-col gap-5'>
            <form onSubmit={handleSubmit} className='flex flex-col gap-4 w-full'>
              <Input
                type="text"
                placeholder={t('signin.email')}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={isLoading}
              />
              <Input
                type="password"
                placeholder={t('signin.password')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
              />
              <LoaderButton isLoading={isLoading} text={t('signin.signin')} />
            </form>
            <p className='text-sm text-muted-foreground text-center text-red-500'>{t('signin.no_account_warning')}</p>
          </CardContent>
        </motion.div>
      </Card>
    </motion.div>
  )
}

export default SignIn;