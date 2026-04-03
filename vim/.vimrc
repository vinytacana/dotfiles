set nocompatible
syntax on
set number
set tabstop=4
set shiftwidth
set autoindent

" === configuração de busca
set ignorecase
set smartcase
set hlsearch


" === plugins

call plug#begin('~/.vim/plugged')

Plug 'preservim/nerdtree'
Plug 'vim-airline/vim-airline'
Plug 'tpope/vim-fugitive'
Plug 'ycm-core/YouCompleteMe', {'do': './install.py --clangd-completer'}
Plug 'octol/vim-cpp-enhanced-highlight'
Plug 'puremourning/vimspector'
Plug 'cdelledonne/vim-cmake'
Plug 'SirVer/ultisnips'
Plug 'honza/vim-snippets'


call plug#end()


" === Configuração de Plugins

let g:NERDTreeShowHidden = 1
nnoremap <C-n> :NERDTreeToggle<CR>

