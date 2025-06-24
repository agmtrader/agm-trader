import { NextAuthOptions } from "next-auth"
import GoogleProvider from 'next-auth/providers/google'
import CredentialsProvider from "next-auth/providers/credentials"
import { LoginUserWithCredentials } from "./api"

const defaultScopes = "users/read users/update accounts/create accounts/read accounts/update"

export const authOptions: NextAuthOptions = {

    providers: [
      GoogleProvider({
        clientId: process.env.GOOGLE_CLIENT_ID!,
        clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
        checks: 'none',
        authorization: {
          params: {
            prompt: "consent",
            access_type: "offline",
            response_type: "code",
            scope: "openid https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email"
          }
        }
      }),
      CredentialsProvider({
        name: 'Credentials',
        credentials: {
          email: { label: "Email", type: "text", placeholder: "jsmith@gmail.com" },
          password: { label: "Password", type: "password" }
        },
        async authorize(credentials) {

          if (credentials?.email && credentials?.password) {
            try {

              const user = await LoginUserWithCredentials(credentials.email, credentials.password)
              return user

            } catch (error) {
              throw new Error('Invalid credentials')
            }
          }
          return null
        }
      }),
    ],
    callbacks: {

      async jwt({ token, user }) {

        // Build token from user profile
        if (user) {

          token.sub = user.id
          token.email = user.email || null
          token.name = user.name || null
          token.image = user.image || null
          token.scopes = user.scopes + ' ' + defaultScopes

        }
        
        return token
      },
      async session({ session, token }) {

        if (session?.user) {
          
          if (token.sub) {

            // Build session user profile from token
            session.user.id = token.sub
            session.user.name = token.name || null
            session.user.email = token.email || null
            session.user.image = token.image || null
            session.user.scopes = token.scopes || defaultScopes

          }
          
        }
        return session
      },
      async signIn({ }) {
        return true
      }

    },
    pages: {
      signIn: '/signin',
    },
    session: {
      strategy: 'jwt'
    },
}