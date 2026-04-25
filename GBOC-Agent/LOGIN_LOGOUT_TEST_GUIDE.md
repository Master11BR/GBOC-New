# 🔐 Guia Completo de Teste - Login e Logout

## 🧪 **TESTE PASSO A PASSO**

### ✅ **Etapa 1: Limpar Cache do Navegador**
**IMPORTANTE**: O navegador pode estar usando arquivos antigos em cache!

1. Pressione `Ctrl + Shift + Delete` (ou `Cmd + Shift + Delete` no Mac)
2. Marque:
   - ✅ Cookies e outros dados do site
   - ✅ Imagens e arquivos em cache
3. Período: **Última hora** ou **Todo o período**
4. Clique em **Limpar dados**

**OU MAIS RÁPIDO**:
- Abra DevTools (F12)
- Clique com botão direito no ícone de atualizar
- Escolha: **"Esvaziar cache e atualizar forçadamente"**

---

### ✅ **Etapa 2: Acessar Página de Diagnóstico**

```
http://localhost:9200/auth-diagnostic.html
```

Esta página vai mostrar:
- ✅ Se `gboc-global.js` foi carregado
- ✅ Se `auth_interceptor.js` está ativo
- ✅ Se a função `handleLogout()` existe
- ✅ Status do token e usuário
- ✅ Status da API de autenticação

**Resultado Esperado:**
- Todos os itens com ✅ verde
- Console mostrando logs detalhados

---

### ✅ **Etapa 3: Testar Login**

1. **Acesse a tela de login:**
```
http://localhost:9200/login.html
```

2. **Verifique o modo:**
   - **Se aparecer "Criar Conta"**: É o primeiro acesso (setup mode)
   - **Se aparecer "Entrar"**: Já existe usuário cadastrado

3. **Faça login:**
   - Usuário: `admin` (ou o que você criou)
   - Senha: `sua_senha`
   - Clique em **Entrar**

4. **Deve redirecionar para:**
```
http://localhost:9200/
```

---

### ✅ **Etapa 4: Verificar Botão de Sair**

1. **No dashboard (`/`), procure no canto superior direito:**
   - Deve haver um botão **vermelho** com ícone de saída
   - Texto: **"Sair"**

2. **Passe o mouse sobre o botão:**
   - Tooltip deve aparecer: "Sair"

3. **Se NÃO aparecer:**
   - Abra DevTools (F12) → Console
   - Verifique se há mensagem: `✅ GBOC Global Functions carregado - 11.7c`
   - Se NÃO houver → arquivo `gboc-global.js` não foi carregado (cache!)

---

### ✅ **Etapa 5: Testar Logout**

1. **Clique no botão "Sair"**

2. **Deve aparecer confirmação:**
   ```
   Deseja realmente sair do sistema?
   [Cancelar] [OK]
   ```

3. **Clique em OK**

4. **Resultado esperado:**
   - Token e dados do usuário são removidos do `localStorage`
   - Navegador redireciona para `/login.html`

5. **Verificar no Console (F12):**
   ```
   🚪 handleLogout chamado
   ✅ Confirmação de logout aceita
   🔄 Redirecionando para login...
   ```

---

## 🔧 **DIAGNÓSTICO DE PROBLEMAS**

### ❌ **Problema 1: Botão "Sair" não aparece**

**Causa**: `gboc-global.js` não foi carregado (cache antigo)

**Solução**:
```
1. Limpar cache (Ctrl + Shift + Delete)
2. Atualizar com cache limpo (Ctrl + F5)
3. Verificar no Console: deve aparecer "✅ GBOC Global Functions carregado"
```

**Teste alternativo**:
1. Abra DevTools (F12) → Console
2. Digite: `handleLogout`
3. Se retornar `function` → está OK
4. Se retornar `undefined` → arquivo não foi carregado

---

### ❌ **Problema 2: Logout não funciona ao clicar**

**Causa**: Função não está associada ao botão

**Solução**:
1. Abra DevTools (F12) → Console
2. Teste manual: `handleLogout()`
3. Se funcionar → problema no HTML
4. Se não funcionar → problema no JavaScript

**Verificar no HTML** (DevTools → Elements):
```html
<button class="btn btn-danger" onclick="handleLogout()" title="Sair">
    <i class="fas fa-sign-out-alt"></i> Sair
</button>
```

---

### ❌ **Problema 3: Login não funciona**

**Causa**: `checkAuthStatus()` não é chamado

**Verificar** (`login.html` linha 350):
```javascript
(function(){
    const saved = localStorage.getItem('gboc-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    checkAuthStatus();  // ← DEVE ESTAR AQUI
})();
```

---

### ❌ **Problema 4: Redireciona automaticamente para login**

**Causa**: `auth_interceptor.js` detecta que não está autenticado

**Comportamento correto**:
- Se não houver token → redireciona para `/login.html`
- Se houver token inválido → redireciona para `/login.html`

**Testar**:
1. Faça login
2. Abra DevTools → Application → localStorage
3. Delete manualmente `gboc_token`
4. Tente acessar qualquer página → deve redirecionar para login

---

## 🧪 **TESTES ADICIONAIS**

### 1. **Teste de Cache Buster**
```
http://localhost:9200/static/gboc-global.js?v=11.7c
```
- Deve baixar arquivo atualizado
- Não deve retornar 304 (Not Modified)

### 2. **Teste de Console**
Abra DevTools e verifique:
```javascript
// Deve retornar: function
typeof handleLogout

// Deve retornar: objeto ou null
localStorage.getItem('gboc_token')

// Deve retornar: true ou false
window.fetch.toString().includes('originalFetch')
```

### 3. **Teste de API**
```javascript
// No Console
fetch('/api/auth/status').then(r => r.json()).then(console.log)

// Resultado esperado:
// {
//   "auth_enabled": true,
//   "authenticated": true,
//   "username": "admin",
//   ...
// }
```

---

## 📋 **CHECKLIST FINAL**

Antes de reportar problemas, verifique:

- [ ] Cache do navegador foi limpo
- [ ] Página foi atualizada com `Ctrl + F5`
- [ ] DevTools → Console mostra: `✅ GBOC Global Functions carregado`
- [ ] Botão "Sair" aparece no canto superior direito
- [ ] Função `handleLogout` existe (`typeof handleLogout === 'function'`)
- [ ] Login funciona e redireciona para dashboard
- [ ] Logout funciona e redireciona para login
- [ ] Página de diagnóstico (`/auth-diagnostic.html`) mostra tudo OK

---

## 🚀 **ACESSO RÁPIDO**

| Página | URL |
|--------|-----|
| Login | `http://localhost:9200/login.html` |
| Dashboard | `http://localhost:9200/` |
| Diagnóstico Auth | `http://localhost:9200/auth-diagnostic.html` |
| Schema Check | `http://localhost:9200/schema-check.html` |

---

## 📞 **REPORTANDO PROBLEMAS**

Se após seguir todos os passos ainda houver problemas, forneça:

1. ✅ **Screenshot da página de diagnóstico** (`/auth-diagnostic.html`)
2. ✅ **Console do navegador** (DevTools → Console)
3. ✅ **Resultado de** `typeof handleLogout` no console
4. ✅ **Logs do servidor** (últimas 50 linhas)
5. ✅ **Navegador e versão** (Chrome 120, Firefox 121, etc)

---

**Versão do GBOC Agent:** 11.7c  
**Data:** 2026-04-13  
**Arquivos Críticos:**
- `static/gboc-global.js?v=11.7c`
- `static/auth_interceptor.js?v=11.7c`
- `static/login.html`
- `static/index.html`
- `static/tasks.html`

